# Architecture cible : stockage des resultats et organisation du workspace

Ce document decrit la restructuration complete du pipeline de resultats HydroModPy.
Toutes les sorties passent par deux bases de donnees par projet. Plus aucun fichier
intermediaire ne persiste sur disque apres execution.

---

## 1. Structure cible du workspace

```
workspace/
├── catalog.duckdb                      # registre partage (donnees d'entree + simulation_registry)
├── data/                               # donnees d'entree partagees entre projets
│   ├── dem/
│   ├── geology/
│   ├── hydrometry/
│   ├── hydrography/
│   ├── intermittency/
│   ├── recharge/
│   ├── piezometry/
│   ├── oceanic/
│   └── ...
└── projects/
    └── {project_name}/
        ├── config.toml                 # configuration utilisateur
        ├── project.duckdb              # metadata, timeseries, metriques, provenance, geographic
        └── project_results.zarr.db/    # champs spatiaux (DirectoryStore, extension .db)
```

Apres `hmp run config.toml`, le dossier projet ne contient que ces trois elements.
Pas de `results_stable/`, `results_simulations/`, `results_calibration/`,
pas de `.pkl`, `.npy`, `.tif` persistants.

---

## 2. Les deux bases de donnees projet

### 2.1. project.duckdb (tabulaire)

Contient tout ce qui est requetable par SQL :

| Table | Contenu |
|-------|---------|
| `simulations` | Metadata de chaque run (sim_id, name, solver, status, duration, config_toml JSON, hmp_version, bbox, tags) |
| `timeseries` | Series temporelles ponctuelles (sim_id, station_id, variable, timestamp, value, unit) |
| `budgets` | Bilan par zone (sim_id, timestep, zone_id, component, flux_in, flux_out) |
| `metrics` | Metriques de performance (sim_id, station_id, metric_name, value) |
| `mass_balance_summary` | Bilan de masse global (sim_id, timestep, total_in, total_out, percent_error) |
| `observation_points` | Mapping station → cellule du maillage |
| `input_provenance` | Empreinte des donnees d'entree (variable, source, checksum, stats) |
| `geographic_features` | Entites geographiques (contour BV, outlet, reseau hydro, bbox) stockees en WKB/GeoJSON |
| `geographic_metadata` | Metadata scalaires (catchment_area_km2, crs, outlet_x, outlet_y, n_cells, cell_size...) |

### 2.2. project_results.zarr.db/ (champs spatiaux)

DirectoryStore Zarr v3 avec extension `.db` pour decourager l'ouverture par l'utilisateur.
Compression BLOSC-ZSTD par chunk.

```
project_results.zarr.db/
└── {sim_uuid}/
    ├── mesh/
    │   ├── vertices                    (n_nodes, 2)
    │   ├── face_node_connectivity      (n_cells, max_vertices)
    │   └── z_interfaces                (n_layers+1,)
    ├── head                            (n_timesteps, n_layers, n_cells)
    ├── concentration                   (n_timesteps, n_layers, n_cells)
    ├── derived/
    │   ├── watertable_elevation        (n_timesteps, n_cells)
    │   ├── watertable_depth            (n_timesteps, n_cells)
    │   ├── seepage_areas               (n_timesteps, n_cells)
    │   ├── groundwater_flux            (n_timesteps, n_cells)
    │   └── accumulation_flux           (n_timesteps, n_cells)
    ├── budget/
    │   ├── recharge                    (n_timesteps, n_cells)
    │   ├── drain                       (n_timesteps, n_cells)
    │   └── ...
    └── pathlines/
        ├── x, y, z, time              (n_particles,)
        └── ...
```

Chunking : `(1, n_layers, n_cells)` — un chunk = un timestep. Optimal pour les
requetes par pas de temps (le cas d'usage principal).

---

## 3. Pipeline d'execution

### 3.1. Vue d'ensemble

```
hmp run config.toml
│
├─ Phase 1 : Setup
│  └─ WorkspaceConfig → decouverte workspace, resolution des chemins
│
├─ Phase 2 : Geographic preprocessing (WhiteboxTools in-memory)
│  ├─ Lecture DEM depuis data/
│  ├─ Chaine d'operations en memoire (breach/fill → D8 → accumulation → watershed)
│  ├─ Stockage des resultats finaux dans project.duckdb (geographic_features, geographic_metadata)
│  ├─ Stockage des rasters finaux (DEM clippe, accumulation) dans project_results.zarr.db
│  └─ Option TOML : ecriture des intermediaires sur disque pour debug
│
├─ Phase 3 : Chargement des donnees
│  ├─ DataManagersRuntimeLoader charge depuis data/ et APIs
│  ├─ Enregistrement dans catalog.duckdb (workspace)
│  └─ Donnees chargees en memoire pour le solver
│
├─ Phase 4 : Execution solver
│  ├─ Creation de .solver_scratch/{sim_id}/ (dossier temporaire)
│  ├─ FloPy ecrit les fichiers d'entree MODFLOW dans le scratch
│  ├─ MODFLOW (binaire Fortran) solve → ecrit .hds, .cbc dans le scratch
│  ├─ FloPy lit les outputs depuis le scratch
│  ├─ Extraction → project.duckdb (timeseries, budgets, mass_balance)
│  ├─ Extraction → project_results.zarr.db (head, budget spatial fields)
│  ├─ Calcul des variables derivees → project_results.zarr.db (watertable, seepage...)
│  ├─ Suppression de .solver_scratch/{sim_id}/
│  └─ Repetition pour chaque solver dans le plan (flow → transport)
│
├─ Phase 5 : Finalisation
│  ├─ store.finalize(sim_id, status="completed", duration_s=...)
│  ├─ Mise a jour du simulation_registry dans catalog.duckdb (workspace)
│  └─ Fermeture des connexions DB
│
└─ Phase 6 : Export a la demande (optionnel)
   ├─ Configure dans [simulation.results.export] du TOML
   ├─ Ou via CLI : hmp export --variable watertable_depth --format geotiff
   ├─ Ou via Python : store.export(sim_id, variable, format, path)
   └─ Formats : NetCDF, CSV, GeoTIFF, VTU (ParaView), Shapefile
```

### 3.2. Detail du solver scratch

MODFLOW est un binaire Fortran qui ne peut pas interagir avec les bases de donnees.
L'adapter FloPy gere le cycle de vie du dossier temporaire :

```
Adapter FloPy (Python)              MODFLOW (Fortran)
    │                                     │
    ├── cree .solver_scratch/{sim_id}/    │
    ├── FloPy ecrit inputs (.nam, .dis…) ─┤
    │                                     ├── lecture des inputs
    │                                     ├── resolution numerique
    │                                     ├── ecriture .hds, .cbc, .lst
    ├── FloPy lit .hds/.cbc ──────────────┘
    ├── ResultStore.write_field(head)
    ├── ResultStore.write_budget(...)
    ├── DerivedVariablesComputer(watertable, seepage...)
    ├── supprime .solver_scratch/{sim_id}/
    └── return (rien sur disque)
```

Le scratch est configurable :

```toml
[simulation.results]
keep_solver_files = false                   # defaut : supprimer apres extraction
solver_scratch = ".solver_scratch"          # relatif au projet (defaut)
# solver_scratch = "/scratch/$USER/hmp"    # chemin absolu pour HPC
```

Si `keep_solver_files = true`, le dossier scratch est conserve pour debug.

### 3.3. Geographic preprocessing in-memory

Le backend WhiteboxWorkflows supporte deja le chainage en memoire.
Le pipeline geographic :

```
1. tool.read_raster(dem_path)              → objet raster en memoire
2. tool.breach_depressions_raster(dem)     → corrected DEM (memoire)
3. tool.d8_pointer_raster(corrected)       → flow direction (memoire)
4. tool.d8_flow_accumulation_raster(...)   → accumulation (memoire)
5. tool.snap_pour_points_vector(...)       → outlet snappe (memoire)
6. tool.watershed_raster(direc, outlet)    → masque BV (memoire)
7. Extraction contour BV, surface, bbox    → project.duckdb (geographic_features)
8. Ecriture DEM clippe, accumulation       → project_results.zarr.db (preprocessing group)
```

Aucun fichier intermediaire sur disque. Option TOML pour debug :

```toml
[geographic]
write_intermediates = false     # defaut : tout en memoire
# write_intermediates = true    # ecrit les rasters intermediaires dans preprocessing/
```

Si `write_intermediates = true`, un dossier `preprocessing/` est cree avec les rasters
(meme logique que l'ancien `results_stable/`). Sinon, rien.

---

## 4. Suppression du legacy

### 4.1. Ce qui disparait

| Element | Localisation | Remplace par |
|---------|-------------|-------------|
| `results_stable/` | projet | Geographic → DB + memoire |
| `results_simulations/` | projet | .solver_scratch/ (temp) + DB |
| `results_calibration/` | projet | DB (simulations avec status='calibrated') |
| `results_{model}.pkl` | results_simulations/ | Supprime (rien ne le lit) |
| `*.npy` (watertable, seepage...) | _postprocess/ | project_results.zarr.db |
| `*.tif` (rasters par timestep) | _postprocess/_rasters/ | Export a la demande |
| `_timeseries/*.csv` | _postprocess/ | project.duckdb (timeseries) |
| `_metrics.json` | results_simulations/ | project.duckdb (metrics) |

### 4.2. Ce qui reste inchange

| Element | Raison |
|---------|--------|
| `data/` (workspace) | Donnees d'entree partagees, format standard |
| `catalog.duckdb` (workspace) | Registre des donnees d'entree |
| `config.toml` (projet) | Configuration utilisateur |
| Le solver MODFLOW lui-meme | Binaire Fortran, pas modifiable |

---

## 5. Export a la demande

Trois niveaux, tous appellent `ResultStore.export()` :

### 5.1. TOML auto-export (apres chaque run)

```toml
[simulation.results.export]
netcdf = true                   # export NetCDF-4/UGRID
csv_timeseries = true           # export series temporelles CSV
geotiff = false                 # export GeoTIFF par variable
vtu = false                     # export VTU (ParaView)
shapefile = false               # export Shapefile

[simulation.results.export.variables]
head = true
watertable_depth = true
seepage_areas = true
budget = false
pathlines = false
```

Les exports vont dans `{project}/exports/{sim_id}/`.

### 5.2. CLI on-demand

```bash
# Dernier run
hmp export --variable watertable_depth --format geotiff

# Run specifique
hmp export --sim {sim_id} --variable head --format netcdf --output ./mon_export/

# Tout exporter en CSV
hmp export --format csv

# Lister les runs disponibles
hmp list runs
```

### 5.3. Python API

```python
from hydromodpy.results.store import ResultStore

store = ResultStore("./projects/canut")
sims = store.list_simulations(status="completed")
store.export(sims[0].sim_id, "watertable_depth", "geotiff", "output.tif", timestep=-1)

# Acces direct aux donnees
import numpy as np
head = store.query_field(sim_id, "head", timestep=5)  # np.ndarray
ts = store.query_timeseries(sim_id, station_id="J001", variable="discharge")  # pd.Series
```

---

## 6. Cross-project discovery

Le `catalog.duckdb` au niveau workspace contient une table `simulation_registry`
alimentee par `store.finalize()` :

```sql
SELECT project, name, solver, status, best_nse, duration_s, created_at
FROM simulation_registry
WHERE status = 'completed'
ORDER BY best_nse DESC;
```

Permet de comparer les performances entre projets sans ouvrir chaque `project.duckdb`.

---

## 7. Figures et visualisation

Les suites de figures lisent depuis :
1. **En memoire** pendant l'execution (objets model directement)
2. **Depuis la DB** en mode posthoc (`hmp display config.toml`)

Le code display existant a deja un fallback 3-tiers :
rasters .tif → dicts .npy → ResultStore. Apres migration, seul le ResultStore reste.

```python
# Mode posthoc
store = ResultStore(project_path)
head = store.query_field(sim_id, "head", timestep=0)
wt = store.query_field(sim_id, "watertable_depth", timestep=0, subgroup="derived")
```

Les figures vont dans `{project}/figures/` (optionnel, controle par `[display]`).

---

## 8. Reproductibilite

Chaque simulation enregistre dans `project.duckdb` :
- Le TOML complet (`config_toml JSON` dans la table `simulations`)
- La version HydroModPy (`hmp_version`)
- L'empreinte des donnees d'entree (`input_provenance` : checksum, stats, source)
- Le hash de config (`config_hash` dans `simulation_registry`)

Permet de re-executer exactement la meme simulation ou de detecter les re-runs identiques.

---

## 9. Plan d'implementation par etapes

### Etape 1 : Supprimer le legacy post-processing
- Retirer `_persist_pre_run_payload()` (.pkl)
- Retirer `model_modflow.post_processing()` (.npy, .tif)
- Utiliser `.solver_scratch/` au lieu de `results_simulations/`
- Cleanup du scratch apres extraction ResultStore
- Verifier que `hmp run` ne produit que project.duckdb + project_results.zarr.db

### Etape 2 : Migrer le geographic preprocessing
- Passer le pipeline geographic en mode full in-memory (whitebox workflows backend)
- Stocker les outputs finaux dans project.duckdb (geographic_features) et zarr (rasters)
- Supprimer la creation de `results_stable/`
- Option `write_intermediates` pour debug

### Etape 3 : Export et figures
- Implementer `hmp export` CLI
- Migrer les suites display pour lire exclusivement depuis ResultStore
- Supprimer les fallbacks .npy/.tif dans le code display

### Etape 4 : Nettoyage workspace
- Retirer `results_simulations/`, `results_calibration/` du PathRegistry
- Retirer les `create_folder()` eagerly dans Workspace.__init__
- Mettre a jour `hmp init` et `hmp new`
- Renommer extension zarr en `.zarr.db`

### Etape 5 : Calibration (futur)
- Table `calibration_traces` dans project.duckdb
- Integration avec l'optimiseur
- Hot path RAM-only, cold path vers DB
