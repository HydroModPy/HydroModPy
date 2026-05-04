# Bases de données et workflows

Document de référence pour comprendre comment HydroModPy persiste,
indexe et relit ses données. Il couvre les deux bases distinctes
(catalogue de sortie et cache d'entrée), leur articulation avec les
workflows et les garanties de cohérence.

Liens :
[simulation_catalog_architecture.md](simulation_catalog_architecture.md),
[parquet_lakehouse_architecture.md](parquet_lakehouse_architecture.md),
[parquet_lakehouse_concurrency.md](parquet_lakehouse_concurrency.md),
[schema_evolution.md](schema_evolution.md),
[calibration_guide.md](calibration_guide.md),
[CLI.md](CLI.md),
[glossary.md](glossary.md).

## 1. Vue d'ensemble

Un workspace HydroModPy contient deux bases indépendantes, chacune
adossée à un fichier DuckDB distinct :

| Rôle | Fichier | Code | Ce qu'elle contient |
|---|---|---|---|
| Catalogue de sortie | `hydromodpy.duckdb` | `hydromodpy/results/catalog.py` | Métadonnées des simulations, paramètres, métriques, provenance, calibration, géographie |
| Cache d'entrée | `data/cache.duckdb` | `hydromodpy/data/registry/catalog_duckdb.py` | Index des données d'entrée (hydrométrie, piézométrie, géologie, climat), artefacts et provenance des fetchs |

Les données lourdes ne tiennent pas dans DuckDB. Trois formats
complémentaires sont utilisés :

- **Zarr** (`simulations/<basename>.zarr/`, puis éventuellement
  `.zarr.zip`) pour les champs spatiaux 3D produits par le solveur
  (charges, budgets, dérivés).
- **Parquet** (`simulations/<basename>.parquet/`) pour les séries temporelles
  append-only, les budgets et bilans de masse, exposés en vues SQL.
- **Fichiers d'entrée** (`data/<variable>/`) bruts (CSV, NetCDF, TIFF)
  référencés par le cache DuckDB.

Disposition physique :

```
workspace/
├── hydromodpy.duckdb                 # catalogue de sortie
├── data/
│   ├── cache.duckdb                  # cache d'entrée
│   └── <variable>/                   # fichiers bruts
│       ├── dem/
│       ├── geology/
│       ├── hydrometry/
│       └── ...
├── simulations/
│   ├── <basename>.zarr/              # champs spatiaux
│   ├── <basename>.zarr.zip           # Zarr packé après finalize
│   └── <basename>.parquet/
│       ├── timeseries.parquet
│       ├── budgets.parquet
│       └── mass_balance.parquet
├── projects/
│   └── <nom>/project.toml
└── configs/                          # TOML utilisateur
```

## 2. Catalogue de sortie

Code principal :

- `hydromodpy/results/catalog.py` : classe `SimulationCatalog`.
- `hydromodpy/results/catalog_schema.py` : DDL (tables, vues, index).
- `hydromodpy/results/zarr_store.py` : classe `SimulationZarr`.
- `hydromodpy/results/run.py` : classe `Run`.
- `hydromodpy/results/simulation_group.py` : classe `SimulationGroup`.
- `hydromodpy/results/views.py` : vues catchment-scale calculées à la
  volée.
- `hydromodpy/core/io/db_retry.py` : helpers de retry DuckDB.
- `hydromodpy/results/catalog/storage_paths.py` : normalisation et
  résolution des noms de fichiers.

### 2.1. Tables DuckDB

Toutes les tables sont créées par `ensure_schema` sur l'ouverture du
catalogue.

| Table | Rôle | Clé primaire |
|---|---|---|
| `simulations` | Ligne par run : projet, solveur, maillage, bbox, période, config, timing | `sim_id` (UUID) |
| `parameters` | Paramètres homogènes ou par zone | `(sim_id, param_name, zone_id)` |
| `metrics` | Métriques par station et variable | `(sim_id, station_id, variable, metric_name)` |
| `observation_points` | Stations projetées sur la grille | `(sim_id, station_id)` |
| `provenance` | Fingerprints SHA-256 des entrées utilisées | composite (sim_id, variable, source_ref) |
| `calibration_sessions` | Session d'optimisation | `session_id` (UUID) |
| `calibration_iterations` | Trace complète des trials | `(session_id, iteration)` |
| `geographic_features` | Vecteurs vectoriels par simulation | `(sim_id, feature_name)` |
| `geographic_metadata` | Clé/valeur géographique | `(sim_id, key)` |
| `runs_environment` | Snapshot env Python et OS au run | `sim_id` |
| `tags` | Étiquettes libres | `(sim_id, tag)` |
| `stations`, `observations` | Référentiel et relevés bruts | composites |
| `tracked_files` | Fichiers d'entrée tracés par simulation | `(sim_id, role, canonical_path)` |

Contraintes notables sur `simulations` :

- `status IN ('pending', 'running', 'completed', 'failed', 'aborted')`.
- `flow_regime IN ('steady', 'transient', 'steady_then_transient')`.
- `mesh_topology IN ('dis', 'disv', 'disu')`.
- Index unique `(project, name)`, index sur `mesh_hash`,
  `geographic_fingerprint`, `config_hash`, `config_source`, `status`,
  `created_at`.

### 2.2. Vues Parquet

Trois vues exposent les rangées haute volumétrie stockées en Parquet par
simulation :

| Vue | Colonnes clés | PK logique |
|---|---|---|
| `timeseries` | `sim_id`, `station_id`, `variable`, `datetime`, `value`, `unit`, `qflag` | `(sim_id, station_id, variable, datetime)` |
| `budgets` | `sim_id`, `timestep`, `zone_id`, `component`, `flux_in`, `flux_out`, `unit` | `(sim_id, timestep, zone_id, component)` |
| `mass_balance` | `sim_id`, `timestep`, `total_in`, `total_out`, `storage_in`, `storage_out`, `percent_error`, `unit` | `(sim_id, timestep)` |

`ensure_parquet_views` définit deux formes possibles par vue :

- Si au moins un fichier Parquet existe sous
  `simulations/*.parquet/<vue>.parquet` : la vue est un
  `read_parquet(..., union_by_name=true)`.
- Sinon : vue typée vide, pour que `SELECT ... FROM timeseries` reste
  valide sur un workspace neuf.

La vue est rafraîchie à la première écriture qui crée un fichier
Parquet, puis à la suppression du dernier fichier.

Les types DuckDB `UUID` et `TIMESTAMPTZ` round-trippent via l'encodage
natif Parquet. Aucun cast n'est nécessaire côté lecture.

### 2.3. Vues utilitaires

`catalog_schema.py` définit aussi des vues dénormalisées :

- `v_simulation_summary` : une ligne par simulation avec NSE, KGE, RMSE,
  R² agrégés.
- `v_best_per_project` : meilleure simulation par projet selon NSE.
- `v_metrics_wide` : pivot des métriques sur les noms connus (`nse`,
  `kge`, `rmse`, `r2`, `bias`, `pbias`, `mae`, `mse`).
- `v_params_wide` : paramètres pivotés comme MAP.

### 2.4. Stores Zarr

Chaque simulation dispose d'un store Zarr (ou `.zarr.zip` après
finalisation) regroupant les champs spatiaux. Groupes racine :

- `mesh/` : topologie UGRID (`vertices`, `face_node_connectivity`,
  `z_interfaces`, `surface_top`).
- `head/` : charges hydrauliques `(n_timesteps, n_layers, n_cells)`.
- `derived/` : champs dérivés (`watertable_elevation`,
  `watertable_depth`, `seepage_areas`, `accumulation_flux`).
- `budget/` : composantes spatiales (recharge, drain, quaq, qstor).
- `pathlines/` : trajectoires de particules (optionnel).
- `geographic/` : rasters (DEM, géologie) et vecteurs (via Parquet
  sidecar).
- `forcing/` : forçages météo stockés pour audit.

Compression : BLOSC-ZSTD `clevel=3`. Chunking équilibré calculé par
`_balanced_chunks_1d` et `_balanced_chunks_2d` pour viser environ 1 MiB
par chunk.

Conventions : CF-1.11 plus UGRID-1.0 sont déclarés dans les attributs
racines. L'encodage par variable suit `field_registry.FIELD_REGISTRY`
(`standard_name`, `units`, `cell_methods`, `grid_mapping`, `shape`).

### 2.5. Parquet lakehouse

Mécanique d'écriture (`_atomic_write_parquet`) :

1. Enregistrer le DataFrame candidat sur la connexion DuckDB sous
   l'alias `_hmp_insert`.
2. Construire une requête SELECT avec types DuckDB explicites et ordre
   de colonnes déterministe. Si un fichier cible existe déjà, la requête
   fait `UNION ALL BY NAME` avec l'existant, puis applique
   `QUALIFY ROW_NUMBER() OVER (PARTITION BY <PK> ORDER BY priority DESC) = 1`
   pour reproduire la sémantique `INSERT OR REPLACE`.
3. Écrire via `COPY (<select>) TO '<target>.tmp' (FORMAT PARQUET)`.
4. Promouvoir le fichier avec `os.replace`, atomique sous POSIX.
5. Rafraîchir les vues (`ensure_parquet_views`) si c'est le premier
   fichier pour cette vue.
6. Désenregistrer l'alias `_hmp_insert`.

Un crash entre les étapes 3 et 4 laisse un `.tmp` orphelin. Le glob des
vues ne matche que `*.parquet`, donc l'orphelin n'est pas visible. `hmp
doctor` peut signaler ces orphelins pour nettoyage manuel.

Pour le détail et les raisons (pourquoi Parquet plutôt qu'une table
DuckDB unique, pourquoi pas de partitionnement Hive), voir
[parquet_lakehouse_architecture.md](parquet_lakehouse_architecture.md).

### 2.6. Nommage des fichiers

`catalog.storage_paths.build_storage_basename` construit des basenames
déterministes : `<project_slug>__<name_slug>__<short_uuid>`.

- `sanitize_segment` normalise par NFD + minuscule, garde `[a-z0-9_-]`,
  tronque à 32 caractères.
- `short_uuid` extrait les 8 premiers hex.

Les anciens workspaces peuvent avoir `storage_basename NULL` ; dans ce
cas le fallback est l'UUID complet.

### 2.7. API publique de `SimulationCatalog`

Les méthodes suivantes sont le point d'entrée côté écriture (toutes
protégées par `@with_lock_retry`) :

- `register_simulation(...)` : crée ou remplace une ligne `simulations`,
  retourne le `sim_id`. Options `on_collision="replace"|"fail"|"version"`.
- `write_parameters(sim_id, df)` : remplace les paramètres.
- `write_metric(sim_id, station_id, variable, metric_name, value, ...)`.
- `write_timeseries(sim_id, df)` / `write_budgets` / `write_mass_balances` :
  voie Parquet atomique.
- `write_provenance(sim_id, df)` : enregistre fingerprints.
- `write_geographic_feature(sim_id, feature_name, gdf)` : GeoDataFrame
  vers Parquet sidecar dans le Zarr.
- `write_geographic_metadata(sim_id, key, value)`.
- `write_geographic_raster(sim_id, name, array, metadata)` : raster vers
  Zarr `geographic/<name>`.
- `finalize(sim_id, ...)` : ferme proprement, passe `status` à
  `completed`, optionnellement pack le Zarr en `.zarr.zip`.
- `delete(sim_id, remove_storage=True)` : efface la ligne, ses dépendances,
  le Zarr et le répertoire Parquet. Avec `remove_storage=False`, seuls les
  enregistrements DuckDB sont supprimés.

Côté lecture :

- `__getitem__(ref)` : résolution par UUID complet, préfixe (>= 4 hex)
  ou alias unique `(project, name)`.
- `find(**filters)` : retourne un `SimulationGroup`. Filtres possibles :
  `project`, `solver`, `status`, `flow_regime`, `mesh_topology`,
  bornes métriques (`nse_gt=`, `kge_ge=`, ...), tags.
- `best(project, metric="nse")` : meilleur run du projet pour la métrique.
- `open_zarr(sim_id)` : retourne un `SimulationZarr`.
- `export_package(sim_id, path)` et `import_package(path)` : voir §2.9.

Toutes les méthodes s'utilisent aussi via un context manager :
`with SimulationCatalog(workspace) as catalog: ...` ferme la connexion
DuckDB proprement.

### 2.8. `Run` et `SimulationGroup`

`Run` est un handle en lecture seule renvoyé par
`catalog[sim_id]`, `catalog.best(...)` ou par l'itération d'un
`SimulationGroup`. Propriétés et méthodes :

- Métadonnées : `sim_id`, `name`, `project`, `solver`, `status`,
  `n_cells`, `n_layers`, `n_timesteps`, `duration_s`, `tags`, `config`.
- Tabulaire : `parameters`, `metrics`, `provenance` (DataFrames).
- Séries : `timeseries(variable, station, period=None)`.
- Bilan : `budget(component, zone_id, period)`, `mass_balance`.
- Champs spatiaux : `field(variable, timestep, layer=None)`,
  `fields(variable)` (stack), `at(timestep, layer)` chainable.
- Maillage : `mesh` (dict vertices/connectivité), `grid` (métadonnées
  cellulaires).
- Géographie : `dem`, `catchment_mask`, `geographic(feature_name)`,
  `geographic_raster(name)`.
- Vues à la volée : `saturated_fraction`, `drainage_density`,
  `persistence`, `catchment_mean`, `recharge_forcing` (voir
  `views.py`).

`SimulationGroup` expose `parameters`, `metrics` (DataFrames larges),
`compare(metric)`, `sort_by`, `best`, `worst`, `to_dataframe`,
`to_csv`, `to_xarray` (stack multi-simulation). Filtrage via
`group.filter(**criteria)`.

### 2.9. Format `.hmp`

`export_package(sim_id, path)` produit une archive `tar.zst` autonome
(code : `hydromodpy/results/exporters/hmp_package.py`) :

- `manifest.json` : version, sim_id, liste de fichiers plus SHA-256 par
  entrée.
- `catalog_snapshot.duckdb` : snapshot des lignes pertinentes
  (`simulations`, `parameters`, `metrics`, `provenance`,
  `geographic_features`, `geographic_metadata`).
- `simulation.zarr.zip` : Zarr packé de façon déterministe.
- `parquet/` : `timeseries.parquet`, `budgets.parquet`,
  `mass_balance.parquet` matérialisés.
- `geographic/` : cache raster content-addressable.
- `README.md` : résumé généré.

`import_package(path)` inverse l'opération dans un workspace cible, avec
détection de collision d'UUID (`on_collision="replace"|"fail"|"version"`).

### 2.10. Exporters supplémentaires

`hydromodpy/results/exporters/` contient en plus :

- `netcdf.py` : export CF-compliant multi-dim.
- `csv.py` : séries temporelles tabulaires.
- `vtu.py` : visualisation ParaView.
- `geotiff.py` : rasters SIG.
- `shapefile.py` : vecteurs SIG.

Chacun expose un point d'entrée `export_<format>(run, path, ...)`.

## 3. Cache d'entrée

Code principal :

- `hydromodpy/data/registry/catalog_duckdb.py` : classe
  `DataCatalogDuckDB`.
- `hydromodpy/data/base_manager.py` : `BaseVariableManager`.
- `hydromodpy/data/variables/<variable>/` : managers concrets.
- `hydromodpy/data/planner.py` : `DataPlanner`.
- `hydromodpy/data/plan.py` : `DataLoadPlan`.

### 3.1. Tables DuckDB

| Table | Rôle |
|---|---|
| `entries` | Index des fichiers cachés : `variable`, `source`, `station_id`, bbox, période, unité, `file_path`, `file_mtime`, `is_custom`, `fetch_metadata` (JSON) |
| `api_coverage` | Couverture spatiale/temporelle connue par fournisseur |
| `artifacts` | Artefacts construits par run : `sim_id`, `variable`, `artifact_type`, `path`, `sha256`, `size_bytes` |
| `provenance` | Logs de transformation : `artifact_id`, `input_hash`, outil, version, `parameters_json` |
| `stations` | Inventaire des stations : `station_id`, `variable`, `source`, lat/lon/z, nom, périodes |
| `coverage` | Couverture par variable et source (région WKT, période, nombre de stations) |
| `failures` | Erreurs de fetch : `variable`, `source_ref`, `error_type`, message, horodatage |
| `validation_reports` | Audit schéma : `artifact_id`, `schema_name`, `passed`, erreurs JSON |

Index : `ix_entries_var_src_station` sur `(variable, source,
station_id)`, `ix_entries_bbox` sur la bbox, `ix_artifacts_sha256` pour
la déduplication, `ix_provenance_artifact` pour le suivi.

### 3.2. Contrat `BaseVariableManager`

Une variable par manager. Attributs de classe :

- `VARIABLE_NAME: str` : identifiant canonique (`hydrometry`,
  `piezometry`, `geology`, `dem`, `precipitation`, `etp`, ...).

Point d'entree public :

```python
store = DataStore(
    project_extent=(x1, y1, x2, y2),
    project_period=(start, end),
)
result = store.load_hydrometry(config)
```

Contrat manager interne :

- `load() -> LoadResult` : itère les sources configurées, déduplique via
  `catalog`, renvoie un `LoadResult` normalisé.
- `_fetch_from_source(source_cfg)` : abstrait, implémenté par chaque
  manager concret.

Variables actuellement implémentées (répertoire
`hydromodpy/data/variables/`) : `dem`, `etp`, `geology`, `humidity`,
`hydrography`, `hydrometry`, `intermittency`, `oceanic`, `piezometry`,
`precipitation`, `radiation`, `recharge`, `runoff`, `soil_moisture`,
`temperature`, `water_quality`, `wind`, plus un
`timeseries_variable_config.py` partagé.

### 3.3. Sources

Chaque manager délègue à un ou plusieurs `DataSource`. Les sources
concrètes (Hub'Eau, SIM2, custom file, BRGM) sont enregistrées au niveau
du manager correspondant, via un registre par variable.

Exemples :

- Hub'Eau pour l'hydrométrie et la piézométrie : cache sur `(variable,
  source, station_id, période)`.
- SIM2 / Météo-France (EDR API) pour précipitations, ETP, humidité,
  température, rayonnement.
- Fichiers custom : CSV, NetCDF, GeoTIFF, Shapefile. Dispatch par
  extension.

Le cache déduplique via `entries.file_path` plus `file_mtime`. Les
nouveaux téléchargements écrivent d'abord un fichier sous
`data/<variable>/`, puis insèrent la ligne.

### 3.4. Planner et plan

`DataPlanner.build(config, domain_zone_ids, domain_support_provider_names,
flow_active_bc, requested_spatial_support_ids, raw_toml)` résout les
managers à activer pour un run. Résultat immuable : `DataLoadPlan` avec
`explicit_types`, `inferred_types`, `reasons_by_type`.

Règles d'inférence (V3) :

- `domain.zone_ids` contient `geology` : active `geology`.
- `domain.supports` fournisseur `geology` : active `geology`.
- `flow.active_bc` contient `stream` : active `hydrography`.
- `flow.active_bc` contient `ocean` : active `oceanic`.

Mode `inference_mode="strict"` : toute inférence requiert une section
`[data.<type>]` explicite (sauf défauts géologie). Mode `"warn"` :
inférences autorisées avec log informatif.

## 4. Interactions entre workflows et bases

Les workflows CLI sont détaillés dans [CLI.md](CLI.md). Voici leur
interaction avec les deux bases.

### 4.1. `simulation`

Pipeline standard `hmp run config.toml` (workflow implicite ou
`workflow = "simulation"`), code `hydromodpy/workflow/pipelines/simulation.py`.

Phase de préparation :

1. `step_setup` : initialise le contexte.
2. `step_spatial_supports(phase="setup")` : config des supports.
3. `step_data_loading` :
   - Ouvre le cache d'entrée en lecture (`DataCatalogDuckDB`).
   - Les managers appellent `load()`. En miss, téléchargement puis
     insertions dans `entries`, `stations`, `coverage`, parfois
     `failures`.
4. `step_spatial_supports(phase="data")` : branchement données
   chargées.
5. `step_mesh` puis `step_mesh_input` : construction du maillage.

Phase d'exécution :

6. `step_open_store` :
   - Ouvre le catalogue de sortie.
   - `register_simulation(...)` en `@with_lock_retry`.
   - Crée `simulations/<basename>.zarr/` via `SimulationZarr.create`.
7. Boucle solveur : le `SolverAdapter` produit ses sorties natives dans
   un scratch dir.
8. `step_ingest_run_results` :
   - Zarr : `write_field` pour `head`, `budget`, `derived`.
   - Parquet : `write_timeseries`, `write_budgets`, `write_mass_balances`.
   - DuckDB : `write_parameters`, `write_metric`,
     `register_observation_points`.
9. `step_write_provenance` : insertion dans `provenance`.
10. `step_finalize_store` : `finalize(sim_id)` met `status='completed'`,
    rafraîchit les vues Parquet, pack optionnel du Zarr.

### 4.2. `calibration`

Code `hydromodpy/calibration/`. Trace complète via
`CalibrationPersistence` (`persistence.py`).

- `start_session()` : `INSERT INTO calibration_sessions` en
  `@with_lock_retry`.
- Pour chaque trial :
  1. L'optimiseur propose un jeu de paramètres.
  2. Si `params_hash` est présent dans `calibration_iterations` de la
     session courante ou d'une précédente : réutilisation du `sim_id` et
     des métriques, `from_cache=True`.
  3. Sinon, exécution d'une simulation complète (même pipeline qu'en
     §4.1). Les écritures solveur ne sont faites que pour les trials
     promus (`save_runs`).
  4. `append_iteration()` insère une ligne dans `calibration_iterations`
     en `ON CONFLICT (session_id, iteration) DO UPDATE`, ce qui rend
     l'écriture idempotente.
- Fin de session : passage au statut `completed`, écriture éventuelle
  d'un rapport HTML.

L'écriture des iterations est sérielle par trial ; le verrou DuckDB est
pris puis relâché par trial. Une session peut donc tourner en parallèle
d'autres lectures sans risque de corruption.

Pour les détails (paramètres, objectifs, optimizers, pièges), voir
[calibration_guide.md](calibration_guide.md).

### 4.3. `batch`

Campagne régionale : expansion site × recette × solveur. Code
`hydromodpy/analysis/batch/`.

- Sites exécutés en parallèle, un par process.
- Chaque site dispose de son propre `<basename>.zarr/` et
  `<basename>.parquet/`, donc pas de contention disque entre sites.
- Les écritures DuckDB (`register_simulation`, `write_*`) sont
  sérialisées par le verrou fichier, avec retry exponentiel via
  `@with_lock_retry`.
- L'agrégation en fin de batch se fait via SQL, sans lock contention
  en lecture.

### 4.4. `overview` et `mesh`

Workflows d'inspection et de préparation :

- `overview` (`workflow/pipelines/overview.py`) : lit le cache d'entrée
  pour vérifier la disponibilité des données, produit un rapport HTML
  ou JSON. **N'écrit rien** dans le catalogue de sortie.
- `mesh` (`workflow/pipelines/mesh.py`) : charge les données nécessaires
  au maillage (DEM, géologie si conformité demandée), produit le
  maillage et l'exporte. `register_simulation(..., status='mesh_only')`
  et écriture Zarr `mesh/`. **Aucune ligne** dans `timeseries`,
  `budgets` ou `mass_balance`.

## 5. Concurrence et robustesse

Code : `hydromodpy/core/io/db_retry.py`.

### 5.1. Verrou DuckDB

DuckDB prend un verrou de writer unique sur le fichier au `connect()`.
Perdre la course lève `duckdb.IOException`.

Politique de retry :

- `connect_with_retry(db_path, retries=8, backoff=0.05)` : utilisé par
  `SimulationCatalog.__init__`. Délais croissants (0.05, 0.1, 0.2, 0.4,
  0.8, 1.6, 3.2, 6.4 secondes, total environ 13 s).
- `@with_lock_retry(retries=8, backoff=0.05)` : décore toutes les
  méthodes d'écriture du catalogue (register, write_parameters,
  write_metric, write_provenance, register_observation_points,
  register_tracked_files, write_geographic_feature, finalize, delete,
  plus les trois writers Parquet).

Les lectures ne retentent pas. Un reader qui heurte le verrou lève
immédiatement. Aucun code ne s'appuie aujourd'hui sur des lectures
concurrentes d'écritures.

### 5.2. Atomicité Parquet

Voir §2.5 pour le détail.

- Écriture dans un `.tmp` sibling, `os.replace` atomique.
- Fusion par `UNION ALL BY NAME` plus `QUALIFY ROW_NUMBER`,
  équivalent à `INSERT OR REPLACE` sur la PK.
- Le glob des vues ignore les `.tmp` : un crash laisse un orphelin
  inoffensif.

### 5.3. Scénarios d'échec

| Étape | Effet | Récupération |
|---|---|---|
| Acquisition du verrou DuckDB | Processus tué verrou pris | Relance ; le verrou est libéré à la fermeture du processus |
| `INSERT` simulations | Row absente ou partielle | Relance ; insertion idempotente sur `sim_id` |
| Écriture Zarr | Chunk incomplet | Append-safe ; la relecture renvoie NaN sur les chunks manquants |
| `COPY TO .tmp` Parquet | Fichier cible inchangé, `.tmp` orphelin | Relance ; `hmp doctor` signale l'orphelin |
| `os.replace` | Opération atomique au niveau OS | Pas de crash mi-swap possible |
| Fermeture DuckDB | WAL DuckDB rollback automatique | Relecture saine |

### 5.4. Commandes de maintenance

- `hmp doctor --toml config.toml` ou `hmp doctor --workspace PATH` :
  - Diagnostic de l'environnement (Python, dépendances, solveurs).
  - Vérification du workspace DuckDB (schéma, simulations).
  - Présence des binaires.
  - Détection des Zarr manquants, des orphelins Zarr/Parquet et des `.parquet.tmp`.

## 6. Lecture côté Python

API publique (voir [glossary.md](glossary.md) pour les types) :

```python
import hydromodpy as hmp

# Ouverture en lecture
catalog = hmp.open("~/workspace")       # SimulationCatalog

# Résolution de simulation
run = catalog["abc12345"]                # préfixe UUID ou UUID complet
run = catalog.best("canut", metric="nse")

# Recherche groupée
group = catalog.find(project="canut", nse_gt=0.7)
best = group.best("nse")
worst = group.worst("nse")

# Accès aux données
head_t12 = run.field("head", timestep=12)
q = run.timeseries("discharge", station="__outlet__")
ts = run.timeseries("head", station="P01", period=("2010-01-01", "2015-01-01"))
budget = run.budget(component="recharge")
mb = run.mass_balance

# Vues catchment-scale (calculées à la volée depuis le Zarr)
sat = run.saturated_fraction(threshold=0.0)
dden = run.drainage_density()
rch = run.recharge_forcing()

# Géographie
gdf = run.geographic("stations")
dem = run.dem
mask = run.catchment_mask

# Pivot multi-simulation
df = group.to_dataframe(
    params=["thickness", "k_brgm"],
    metrics=["nse", "kge"],
)
group.to_csv("output.csv")
da = group.to_xarray("head", dim="sim")

# Rendu
run.plot("watertable_map", save_path="~/figures/")

# Partage entre workspaces
catalog.export_package(run.sim_id, "~/share/run.hmp")
catalog.import_package("~/share/other.hmp")
```

`SimulationCatalog` est un context manager ; en dehors de ce modèle,
appeler `catalog.close()` pour libérer le verrou.

## 7. Flux récapitulatif

Diagramme synthétique d'une simulation :

```
[TOML config] --> hmp run
    | read
    v
[data/cache.duckdb] <--- fetch --- [Hub'Eau, SIM2, fichiers custom]
    | load
    v
[runtime: WorkflowContext]
    | execute
    v
[solver scratch dir]
    | ingest
    v
[hydromodpy.duckdb] (metadata)
[simulations/<basename>.zarr/] (champs)
[simulations/<basename>.parquet/] (séries)
    | read
    v
[Run, SimulationGroup, figures, exports]
```

La séparation en deux bases DuckDB est motivée par l'indépendance des
cycles de vie : le cache d'entrée survit aux simulations et sert
plusieurs runs ; le catalogue de sortie évolue à chaque run. Les deux
peuvent être inspectés indépendamment via `hmp doctor` ou directement
en SQL (`duckdb <fichier.duckdb>`).
