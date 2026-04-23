# Architecture du Simulation Catalog

Ce document décrit l'architecture complète du stockage, de l'accès aux
données et de l'API Python pour HydroModPy.

Principe fondamental : la **simulation** est l'entité première. Le concept
de « projet » est un label, pas un dossier. Une seule base DuckDB contient
toutes les simulations du workspace.

Liens : [glossary.md](glossary.md),
[parquet_lakehouse_architecture.md](parquet_lakehouse_architecture.md),
[parquet_lakehouse_concurrency.md](parquet_lakehouse_concurrency.md),
[parquet_lakehouse_migration_guide.md](parquet_lakehouse_migration_guide.md),
[schema_evolution.md](schema_evolution.md),
[calibration_guide.md](calibration_guide.md).

Note v0.6 (refactor Parquet lakehouse) : les tables `timeseries`,
`budgets` et `mass_balance` ne sont plus stockées dans
`hydromodpy.duckdb`. Elles vivent désormais en Parquet par simulation
sous `simulations/<uuid>.parquet/`, exposées comme des vues DuckDB du
même nom afin que le code SQL existant reste valide.

## 1. Structure physique du workspace

```
workspace/
├── hydromodpy.duckdb              # source de verite unique (toutes les simulations)
├── data/
│   ├── cache.duckdb               # cache des donnees d'entree (API + custom index)
│   └── <variable>/                # fichiers bruts (CSV, NC, TIF)
│       ├── dem/
│       ├── geology/
│       ├── hydrometry/
│       ├── piezometry/
│       ├── recharge/
│       └── ...
├── simulations/                   # un Zarr par simulation (isolation physique)
│   ├── <uuid-aaa>.zarr/
│   ├── <uuid-bbb>.zarr/
│   └── ...
└── configs/                       # TOMLs utilisateur (organisation libre)
    ├── canut/
    │   ├── base.toml
    │   └── run_steady_mf6.toml
    └── nancon/
        ├── base.toml
        └── run_transient_nwt.toml
```

Apres `hmp run config.toml` :
- une ligne est ajoutee dans `hydromodpy.duckdb`
- un dossier `simulations/<uuid>.zarr/` est cree
- aucun fichier intermediaire ne persiste sur disque

## 2. Pourquoi une seule base DuckDB

L'architecture precedente utilisait N `project.duckdb` (un par projet) plus un
`catalog.duckdb` (workspace) avec duplication partielle des metadonnees.

Problemes identifies :
- `simulation_registry` dans catalog.duckdb etait ecrit mais jamais lu en production
- les requetes cross-projet necessitaient d'ouvrir N stores separement
- la calibration et le batch contournaient le store (JSONL, CSV sur disque)
- pas de table normalisee pour les parametres (impossible de faire du ML directement)

Avec une seule base :
- comparaison inter-simulations = un simple `WHERE`
- comparaison inter-bassins = un `GROUP BY project`
- ML/deep learning = une requete SQL retourne un DataFrame pret pour sklearn/pytorch
- pas de duplication, pas d'incoherence entre fichiers

## 3. Schema DuckDB : hydromodpy.duckdb

### 3.1. simulations

Table centrale. Une ligne = un run complet.

```sql
CREATE TABLE simulations (
    sim_id          UUID PRIMARY KEY,
    name            VARCHAR,
    project         VARCHAR,           -- label libre ("canut", "nancon")
    solver          VARCHAR,           -- modflownwt, modflow6, boussinesq
    solver_category VARCHAR,           -- 'distributed' ou 'integrated'
    flow_regime     VARCHAR,           -- steady ou transient
    n_cells         INTEGER,
    n_layers        INTEGER,
    n_timesteps     INTEGER,
    bbox            DOUBLE[4],
    crs             VARCHAR,
    period_start    VARCHAR,
    period_end      VARCHAR,
    time_unit       VARCHAR,
    status          VARCHAR,           -- running, completed, failed
    duration_s      DOUBLE,
    created_at      TIMESTAMP DEFAULT now(),
    config_toml     JSON,              -- snapshot TOML complete pour reproduction
    config_hash     VARCHAR,           -- SHA-256 (detection doublons)
    zarr_path       VARCHAR,           -- chemin relatif vers le .zarr
    tags            VARCHAR[],
    parent_sim_id   UUID,              -- filiation (rerun, best-of-calibration)
    mesh_hash       VARCHAR,           -- SHA-256 du mesh bundle
    mesh_type       VARCHAR,           -- structured, gmsh_triangular
    notes           VARCHAR
);
```

`solver_category` est derive de `solver` :
- `distributed` : modflownwt, modflow6 (maillage 3D, multi-couche)
- `integrated` : boussinesq (thin-film, mono-couche)

Utilise par le display pipeline pour determiner les figures compatibles.

`parent_sim_id` permet de tracer la filiation :
- calibration best-run → pointe vers la session
- rerun avec overrides → pointe vers le run original
- NULL = run independant

### 3.2. parameters

Table normalisee pour les parametres hydrauliques. Permet les requetes ML directes.

```sql
CREATE TABLE parameters (
    sim_id          UUID REFERENCES simulations,
    param_name      VARCHAR,           -- K, Sy, Ss, recharge_factor
    zone_id         VARCHAR,           -- NULL si homogene, geology_key sinon
    value           DOUBLE,
    unit            VARCHAR,
    parameterization VARCHAR,          -- homogeneous, geology_mapped, exponential
    PRIMARY KEY (sim_id, param_name, zone_id)
);
```

Exemple avec simulation homogene :

```
sim_id   | param_name | zone_id | value  | unit | parameterization
---------|------------|---------|--------|------|-----------------
aaa-111  | K          | NULL    | 1.728  | m/d  | homogeneous
aaa-111  | Sy         | NULL    | 0.05   | -    | homogeneous
```

Exemple avec parametres par lithologie :

```
sim_id   | param_name | zone_id  | value  | unit | parameterization
---------|------------|----------|--------|------|-----------------
bbb-222  | K          | granite  | 0.5    | m/d  | geology_mapped
bbb-222  | K          | schiste  | 2.0    | m/d  | geology_mapped
bbb-222  | Sy         | granite  | 0.02   | -    | geology_mapped
bbb-222  | Sy         | schiste  | 0.08   | -    | geology_mapped
```

Requete ML typique :

```sql
SELECT
    s.sim_id, s.solver, s.project, s.n_cells,
    p_k.value AS K, p_sy.value AS Sy,
    m.value AS nse
FROM simulations s
JOIN parameters p_k  ON s.sim_id = p_k.sim_id  AND p_k.param_name = 'K' AND p_k.zone_id IS NULL
JOIN parameters p_sy ON s.sim_id = p_sy.sim_id AND p_sy.param_name = 'Sy' AND p_sy.zone_id IS NULL
JOIN metrics m       ON s.sim_id = m.sim_id     AND m.metric_name = 'nse'
WHERE s.status = 'completed';
```

### 3.3. timeseries

Series temporelles ponctuelles (stations d'observation, exutoire).

```sql
CREATE TABLE timeseries (
    sim_id      UUID REFERENCES simulations,
    station_id  VARCHAR,
    variable    VARCHAR,       -- head, discharge, concentration
    timestamp   TIMESTAMP,
    value       DOUBLE,
    unit        VARCHAR
);
CREATE INDEX ix_ts ON timeseries (sim_id, station_id, variable, timestamp);
```

Volume typique : ~500-5000 lignes par simulation (nombre de stations x nombre de pas de temps).
Avec 1000 simulations : ~5M lignes. DuckDB gere sans probleme.

### 3.4. budgets

Bilan hydrique par composante et par zone.

```sql
CREATE TABLE budgets (
    sim_id      UUID REFERENCES simulations,
    timestep    INTEGER,
    zone_id     VARCHAR,
    component   VARCHAR,       -- recharge, drain, river, wells, storage
    flux_in     DOUBLE,
    flux_out    DOUBLE,
    unit        VARCHAR DEFAULT 'm3/d'
);
```

### 3.5. mass_balance

Bilan de masse global (verification de la conservation).

```sql
CREATE TABLE mass_balance (
    sim_id        UUID REFERENCES simulations,
    timestep      INTEGER,
    total_in      DOUBLE,
    total_out     DOUBLE,
    storage_in    DOUBLE,
    storage_out   DOUBLE,
    percent_error DOUBLE
);
```

### 3.6. metrics

Metriques de performance par station d'observation.

```sql
CREATE TABLE metrics (
    sim_id      UUID REFERENCES simulations,
    station_id  VARCHAR,
    metric_name VARCHAR,       -- nse, kge, rmse, bias, r2, pbias
    value       DOUBLE,
    PRIMARY KEY (sim_id, station_id, metric_name)
);
```

### 3.7. observation_points

Mapping entre stations d'observation et cellules du maillage.

```sql
CREATE TABLE observation_points (
    sim_id      UUID REFERENCES simulations,
    station_id  VARCHAR,
    x           DOUBLE,
    y           DOUBLE,
    cell_id     INTEGER,
    layer       INTEGER,
    variable    VARCHAR
);
```

### 3.8. provenance

Empreinte des donnees d'entree pour chaque simulation.
Permet de verifier si les donnees source ont change depuis l'execution.

```sql
CREATE TABLE provenance (
    sim_id       UUID REFERENCES simulations,
    variable     VARCHAR,       -- recharge, geology, dem, hydrometry
    source_type  VARCHAR,       -- custom, hubeau, sim2, ign_bdalti
    source_ref   VARCHAR,       -- chemin fichier ou URL API
    checksum     VARCHAR,       -- SHA-256 des donnees
    period_start VARCHAR,
    period_end   VARCHAR,
    n_records    INTEGER,
    stats        JSON           -- {mean, min, max, std}
);
```

### 3.9. calibration_sessions

Metadata d'une session de calibration.

```sql
CREATE TABLE calibration_sessions (
    session_id     UUID PRIMARY KEY,
    best_sim_id    UUID REFERENCES simulations,
    method         VARCHAR,       -- scipy_minimize, nlopt, pymoo
    n_iterations   INTEGER,
    best_objective DOUBLE,
    duration_s     DOUBLE,
    config         JSON,          -- section [calibration] du TOML
    created_at     TIMESTAMP DEFAULT now()
);
```

### 3.10. calibration_iterations

Trace complete des iterations. Ecrite en bulk a la fin de la session
(pas d'ecriture DB pendant l'optimisation, zero overhead sur la vitesse).

```sql
CREATE TABLE calibration_iterations (
    session_id      UUID REFERENCES calibration_sessions,
    iteration       INTEGER,
    parameters      JSON,          -- {K: 1.5, Sy: 0.03}
    objective_value DOUBLE,
    metrics         JSON,          -- {nse: 0.8, rmse: 0.5}
    duration_s      DOUBLE,
    PRIMARY KEY (session_id, iteration)
);
```

Workflow :
1. l'optimiseur tourne en memoire (rapide, pas de DB)
2. a la fin, `INSERT INTO calibration_sessions` (1 ligne)
3. puis `INSERT INTO calibration_iterations` (N lignes, bulk)
4. le best-run est une simulation normale avec `parent_sim_id` pointant vers la session

### 3.11. geographic_features

Entites geographiques vectorielles, rattachees a un projet (bassin versant).

```sql
CREATE TABLE geographic_features (
    project       VARCHAR,
    feature_name  VARCHAR,       -- watershed, river_network, outlet, bbox
    geojson       TEXT,          -- GeoDataFrame serialisee en GeoJSON
    geometry_type VARCHAR,
    crs           VARCHAR,
    properties    JSON,
    PRIMARY KEY (project, feature_name)
);
```

Scope : par projet (bassin), pas par simulation. Toutes les simulations d'un meme
bassin partagent les memes features geographiques.

### 3.12. geographic_metadata

Metadonnees scalaires du bassin versant.

```sql
CREATE TABLE geographic_metadata (
    project VARCHAR,
    key     VARCHAR,               -- catchment_area_km2, crs, outlet_x, dem_resolution...
    value   VARCHAR,
    PRIMARY KEY (project, key)
);
```

## 4. Layout Zarr : standardise, solver-agnostique

Chaque simulation a son propre dossier Zarr. Le nommage des variables est identique
quel que soit le solver (modflownwt, modflow6, boussinesq).

```
simulations/<uuid>.zarr/
├── zarr.json                        # Zarr v3 root metadata
│
├── mesh/
│   ├── vertices                     # (n_nodes, 2|3) float64
│   ├── face_node_connectivity       # (n_cells, max_vpf) int32, -1 = padding
│   └── z_interfaces                 # (n_layers+1,) float64
│
├── head/                            # variable primaire (tous les solvers)
│   ├── 0                            # (n_layers, n_cells) float64
│   ├── 1
│   └── ...N
│
├── concentration/                   # transport (MF6-GWT, MT3DMS) - optionnel
│   └── 0 ... N
│
├── derived/                         # variables calculees, solver-agnostique
│   ├── watertable_elevation/        # (n_cells,) par timestep
│   ├── watertable_depth/            # (n_cells,) par timestep
│   ├── seepage_areas/               # (n_cells,) binaire par timestep
│   ├── outflow_drain/               # (n_cells,) optionnel
│   └── accumulation_flux/           # (n_cells,) optionnel
│
├── budget/                          # champs spatiaux de budget (optionnel)
│   ├── recharge/                    # (n_cells,) par timestep
│   ├── drain/
│   └── ...
│
├── pathlines/                       # trajectoires de particules (MODPATH)
│   ├── x, y, z, time               # (n_particles,)
│   └── ...
│
└── geographic/                      # rasters du bassin
    ├── dem                          # (ny, nx) float64 + attrs {transform, crs, nodata}
    └── geology                      # (ny, nx) int32
```

Compression : BLOSC-ZSTD (clevel=3). Chunking : `(1, n_layers, n_cells)` par timestep.

Convention : les noms de variables sont fixes et documentes ici. Les solver adapters
(OutputAdapter) ecrivent dans ces noms standardises. Le display pipeline lit ces noms
sans savoir quel solver a produit les resultats.

## 5. Cache des donnees d'entree : data/cache.duckdb

Fichier separe de `hydromodpy.duckdb`. Concerne uniquement le cache des donnees
d'entree (API et fichiers custom). Aucun lien avec les simulations.

```sql
CREATE TABLE entries (
    id          INTEGER PRIMARY KEY,
    variable    VARCHAR,           -- dem, geology, hydrometry, recharge...
    source      VARCHAR,           -- hubeau, sim2, ign_bdalti, custom
    station_id  VARCHAR,           -- pour les donnees ponctuelles
    bbox_xmin   DOUBLE,
    bbox_ymin   DOUBLE,
    bbox_xmax   DOUBLE,
    bbox_ymax   DOUBLE,
    crs         VARCHAR,
    date_start  VARCHAR,
    date_end    VARCHAR,
    frequency   VARCHAR,
    unit        VARCHAR,
    source_unit VARCHAR,
    file_path   TEXT,              -- chemin vers le fichier sur disque
    file_mtime  DOUBLE,
    created_at  TIMESTAMP DEFAULT now(),
    is_custom   INTEGER,
    fetch_metadata JSON
);
```

Ce fichier peut etre supprime et reconstruit a tout moment en re-fetchant les donnees.
Il ne contient que des metadonnees + des chemins vers des fichiers dans `data/`.

## 6. Pipeline d'execution

```
hmp run config.toml
│
├─ Phase 1 : Setup
│  ├─ Lecture et validation du TOML (HydroModPyConfig)
│  ├─ Connexion a hydromodpy.duckdb
│  └─ Resolution du workspace (auto-decouverte)
│
├─ Phase 2 : Geographic preprocessing
│  ├─ Pipeline WhiteboxTools en memoire (breach → D8 → accumulation → watershed)
│  ├─ Stockage des features dans hydromodpy.duckdb (geographic_features)
│  ├─ Stockage des rasters dans <uuid>.zarr/geographic/
│  └─ Rien sur disque (sauf option write_intermediates pour debug)
│
├─ Phase 3 : Chargement des donnees
│  ├─ DataManagersRuntimeLoader charge depuis data/ et APIs
│  ├─ Enregistrement dans data/cache.duckdb
│  └─ Donnees chargees en memoire (LoadResult)
│
├─ Phase 4 : Registration
│  ├─ generation sim_id (UUID)
│  ├─ INSERT INTO simulations (status = 'running')
│  ├─ INSERT INTO parameters (normalise depuis le TOML)
│  ├─ INSERT INTO provenance (fingerprints des donnees d'entree)
│  └─ Creation du dossier simulations/<uuid>.zarr/
│
├─ Phase 5 : Execution solver
│  ├─ Creation de .solver_scratch/<uuid>/ (temporaire)
│  ├─ Adapter FloPy ecrit les inputs MODFLOW
│  ├─ MODFLOW resout → .hds, .cbc
│  ├─ Extraction → hydromodpy.duckdb (timeseries, budgets, mass_balance, metrics)
│  ├─ Extraction → <uuid>.zarr/ (head, budget spatial)
│  ├─ Calcul des derived → <uuid>.zarr/derived/
│  ├─ Suppression de .solver_scratch/<uuid>/
│  └─ Repetition pour chaque process (flow → transport)
│
├─ Phase 6 : Finalisation
│  ├─ UPDATE simulations SET status = 'completed', duration_s = ...
│  └─ Fermeture des connexions
│
└─ Phase 7 : Export a la demande (optionnel)
   ├─ Configure dans [simulation.results.export] du TOML
   ├─ Ou via API Python : sim.to_netcdf("head")
   └─ Formats : NetCDF-4/UGRID, CSV, GeoTIFF, VTU, Shapefile
```

## 7. API Python

Trois niveaux d'abstraction. L'utilisateur ne manipule jamais DuckDB directement
sauf s'il le souhaite.

### 7.1. SimulationCatalog : point d'entree

```python
import hydromodpy as hmp

catalog = hmp.open("~/workspace")
```

Explorer les simulations :

```python
catalog.simulations                                    # DataFrame de toutes les sims
catalog.find(project="canut", solver="modflow6")       # filtres nommes
catalog.find(nse_gt=0.7, tags="transient")             # seuils sur metriques
```

Acceder a une simulation :

```python
sim = catalog["<uuid>"]                                # par UUID
sim = catalog.latest("canut")                          # derniere completee du projet
sim = catalog.best("canut", metric="nse")              # meilleure NSE du projet
```

Gerer les simulations :

```python
catalog.delete("<uuid>")                               # supprime DB + Zarr
catalog.delete(project="canut", status="failed")       # suppression groupee
catalog.cleanup(older_than="2025-01-01")               # nettoyage par date
catalog.cleanup(status="failed")                       # nettoyage par statut
```

Import / export :

```python
catalog.export_package("<uuid>", "~/partage/canut_best.hmp")
catalog.import_package("~/partage/colleague_run.hmp")
```

SQL direct (power users, ML) :

```python
catalog.sql("SELECT project, solver, AVG(m.value) ...")   # → DataFrame
catalog.connection                                         # → duckdb.DuckDBPyConnection
```

### 7.2. Simulation : une simulation individuelle

Metadata :

```python
sim = catalog.best("nancon", metric="nse")

sim.id                        # UUID
sim.name                      # nom du run
sim.project                   # "nancon"
sim.solver                    # "modflow6"
sim.solver_category           # "distributed"
sim.flow_regime               # "transient"
sim.status                    # "completed"
sim.created_at                # datetime
sim.duration_s                # temps d'execution
sim.config                    # dict (TOML snapshot complet)
sim.tags                      # ["transient", "sensitivity_K"]
sim.parameters                # DataFrame {param_name, zone_id, value, unit}
sim.metrics                   # DataFrame {station_id, metric_name, value}
sim.provenance                # DataFrame {variable, source, checksum}
```

Donnees :

```python
sim.timeseries("head", station="P01")               # → pd.Series
sim.timeseries("discharge", station="_catchment")    # → pd.Series
sim.budget(component="recharge")                     # → DataFrame
sim.mass_balance                                     # → DataFrame

sim.field("head", timestep=12)                       # → ndarray (n_layers, n_cells)
sim.field("watertable_depth", timestep=-1)           # → ndarray (dernier pas de temps)
sim.mesh                                             # → MeshAccessor (vertices, connectivity)
```

Export cible (chaque methode retourne un Path) :

```python
sim.to_netcdf("head")                                # → head.nc (UGRID CF-compliant)
sim.to_netcdf(["head", "watertable_depth"])           # multi-variable
sim.to_geotiff("watertable_depth", timestep=-1, resolution=50)
sim.to_shapefile("watertable_depth", timestep=-1)
sim.to_csv()                                          # toutes les timeseries
sim.to_vtu("head", timestep=12)                       # ParaView
```

Export geographic :

```python
sim.geographic("watershed").to_file("~/export/mask.shp")
sim.geographic("watershed").to_file("~/export/mask.gpkg")    # GeoPackage aussi
sim.geographic("river_network").to_file("~/export/rivers.gpkg")
sim.geographic_raster("dem").to_geotiff("~/export/dem.tif")
sim.mesh.to_geodataframe()                            # cellules comme polygones GeoDataFrame
```

Figures a la demande :

```python
sim.display_capabilities                              # → ['watertable_map', 'cross_section', ...]
sim.plot("watertable_map")                            # affiche la figure
sim.plot("watertable_map", save="~/figures/")         # sauvegarde PNG
sim.plot_all(save="~/figures/")                       # toutes les figures compatibles
```

Reproduction :

```python
sim.rerun()                                           # relance avec la meme config
sim.rerun(K=2.0, Sy=0.1)                             # relance avec overrides
```

Export complet (package portable) :

```python
sim.export("~/partage/nancon_best.hmp")
# cree un dossier contenant simulation.duckdb + results.zarr/
# le destinataire fait : catalog.import_package("nancon_best.hmp")
```

### 7.3. SimulationGroup : operations groupees

```python
group = catalog.find(project="canut", status="completed")

group.count                                           # nombre de simulations
group.parameters                                      # DataFrame pivot (sim_id x param)
group.metrics                                         # DataFrame pivot (sim_id x metric)
group.compare(metric="nse")                           # tableau comparatif trie
group.best(metric="nse")                              # → Simulation
group.worst(metric="nse")                             # → Simulation
group.sort_by("nse", ascending=False)                 # tri
```

ML-ready :

```python
df = group.to_dataframe()
# colonnes : sim_id, K, Sy, Ss, nse, kge, rmse, solver, n_cells, project...
# directement utilisable par sklearn / pytorch
```

Comparaison inter-bassins :

```python
canut  = catalog.find(project="canut",  status="completed")
nancon = catalog.find(project="nancon", status="completed")

hmp.compare_groups(canut, nancon, by="param_name", metric="nse")
# → DataFrame croise : param x bassin x metric
```

## 8. Display pipeline solver-agnostique

Le display ne connait pas le solver. Il connait :
- `solver_category` (distributed / integrated) pour les figures incompatibles
- la **presence** des variables dans le Zarr pour les capabilities

```python
def get_display_capabilities(sim_metadata, zarr_store):
    caps = ["watertable_map", "budget_chart"]

    if sim_metadata.n_layers > 1:           # distributed seulement
        caps.append("cross_section")

    if sim_metadata.flow_regime == "transient":
        caps.extend(["streamflow", "head_timeseries", "drainage_density"])

    if "concentration" in zarr_store:       # transport disponible
        caps.append("concentration_map")

    if "pathlines" in zarr_store:           # MODPATH disponible
        caps.append("pathlines")

    return caps
```

Figures communes a tous les solvers :
- watertable_map (elevation + profondeur)
- state_triptych (topographie / head / depth)
- budget_chart (bilan par composante)
- recharge_discharge_cumulative

Figures distributed (n_layers > 1) uniquement :
- cross_section (coupe verticale)

Figures transient uniquement :
- streamflow (debit simule vs observe)
- head_timeseries (chronique piezometrique)
- drainage_density (reseau perenne vs intermittent)
- persistency_map (indice de duree d'ecoulement)

Figures conditionnelles :
- concentration_map (si transport actif)
- pathlines (si MODPATH/particules)

## 9. Calibration

### 9.1. Execution (rapide, en memoire)

L'optimiseur tourne sans toucher la DB. Toutes les iterations restent en RAM
(ou en fichiers temporaires locaux si necessaire pour la memoire).

```
CalibrationEngine.run()
├── iteration 1 : eval(K=1.0, Sy=0.05) → NSE=0.65     # en memoire
├── iteration 2 : eval(K=1.5, Sy=0.03) → NSE=0.72     # en memoire
├── ...
├── iteration N : eval(K=1.8, Sy=0.04) → NSE=0.85     # en memoire
└── terminaison (convergence ou max_iter)
```

### 9.2. Persistance (a la fin, en bulk)

```python
session.persist(catalog)
```

Operations :
1. le best-run est execute comme une simulation normale → ligne dans `simulations`
2. `INSERT INTO calibration_sessions` (1 ligne)
3. `INSERT INTO calibration_iterations` (N lignes, bulk insert)
4. la simulation du best-run a `parent_sim_id` qui reference la session

### 9.3. Analyse post-hoc

```python
session = catalog.calibration_session("<session_id>")
session.iterations                    # → DataFrame (iteration, parameters, objective, metrics)
session.best_parameters               # → dict {K: 1.8, Sy: 0.04}
session.convergence_curve             # → Series (iteration → objective)
session.best_simulation               # → Simulation (acces complet aux resultats)
```

```sql
-- Analyse directe en SQL
SELECT iteration, objective_value,
       json_extract(parameters, '$.K') AS K,
       json_extract(parameters, '$.Sy') AS Sy
FROM calibration_iterations
WHERE session_id = '<session_id>'
ORDER BY objective_value;
```

## 10. Import / export de simulations

### 10.1. Format du package .hmp

Un package `.hmp` est un dossier contenant tout le necessaire pour
reconstituer une simulation dans un autre workspace.

```
nancon_best.hmp/
├── simulation.duckdb              # sous-ensemble de hydromodpy.duckdb
│   ├── simulations (1 ligne)
│   ├── parameters
│   ├── timeseries
│   ├── budgets
│   ├── mass_balance
│   ├── metrics
│   ├── observation_points
│   ├── provenance
│   ├── geographic_features
│   └── geographic_metadata
└── results.zarr/                  # copie du <uuid>.zarr/
    ├── mesh/
    ├── head/
    ├── derived/
    └── geographic/
```

### 10.2. Export

```python
sim.export("~/partage/nancon_best.hmp")
```

Internally :
1. `CREATE` un nouveau DuckDB temporaire
2. `ATTACH hydromodpy.duckdb AS src`
3. pour chaque table : `CREATE TABLE ... AS SELECT * FROM src.{table} WHERE sim_id = ?`
4. `geographic_features` et `geographic_metadata` : filtre par `project`
5. copie du dossier Zarr (`shutil.copytree`)

### 10.3. Import

```python
catalog.import_package("~/partage/nancon_best.hmp")
```

Internally :
1. `ATTACH simulation.duckdb AS pkg`
2. pour chaque table : `INSERT INTO {table} SELECT * FROM pkg.{table}`
3. verification : si `sim_id` existe deja, erreur (ou option `force=True`)
4. copie du Zarr dans `simulations/<uuid>.zarr/`
5. mise a jour de `zarr_path` dans la ligne importee

## 11. Concurrence et robustesse

### 11.1. Ecritures pendant l'execution

Les ecritures dans `hydromodpy.duckdb` se font **apres** le solver, pas pendant :
1. `register_simulation` : 1 INSERT (rapide)
2. solver execute (aucune ecriture DB)
3. extraction : N INSERTs timeseries + budgets (sequentiel par simulation)
4. finalize : 1 UPDATE (rapide)

Si deux simulations terminent l'extraction au meme moment, DuckDB serialise
les ecritures via le WAL (Write-Ahead Log). Latence : quelques millisecondes.

### 11.2. Batch parallele

Pour les campagnes batch (10+ simulations paralleles), si la serialisation
WAL devient un goulot :
- option 1 : ecriture dans un DuckDB temporaire par simulation, merge a la fin
- option 2 : les ecritures post-solver sont naturellement decalees dans le temps

En pratique, avec des solveurs qui prennent des minutes a des heures,
la fenetre de collision est negligeable.

### 11.3. Corruption

DuckDB utilise le WAL avec checkpoints periodiques. En cas de crash :
- le WAL est rejoue au prochain `duckdb.connect()`
- les transactions non commitees sont perdues (= le run en cours)
- les simulations deja finalisees sont intactes

Backup : un simple `cp hydromodpy.duckdb hydromodpy.duckdb.bak` suffit.

## 12. Reproductibilite

Chaque simulation stocke :

| Donnee | Table | Champ |
|--------|-------|-------|
| Config TOML complete | simulations | config_toml (JSON) |
| Hash de config (dedup) | simulations | config_hash (SHA-256) |
| Parametres normalises | parameters | param_name, value, unit |
| Empreinte des donnees d'entree | provenance | checksum (SHA-256), stats |
| Hash du mesh | simulations | mesh_hash (SHA-256) |
| Filiation | simulations | parent_sim_id |

Pour relancer une simulation :

```python
sim = catalog["<uuid>"]
sim.rerun()                    # meme config, memes parametres
sim.rerun(K=2.0)               # override d'un parametre
```

`rerun()` reconstruit le TOML depuis `config_toml`, applique les overrides,
et execute une nouvelle simulation avec `parent_sim_id` pointant vers l'originale.

## 13. Ce qui disparait par rapport a l'architecture precedente

| Supprime | Raison |
|----------|--------|
| `project.duckdb` (par projet) | Fusionne dans `hydromodpy.duckdb` |
| `simulation_registry` dans catalog.duckdb | Dead code (jamais lu). Requetes cross-sim natives maintenant |
| `catalog.duckdb` (double role) | Remplace par `data/cache.duckdb` (scope reduit) |
| Concept de projet = dossier | Projet = label dans `simulations.project` |
| `project_results.zarr.db` (multi-sim par projet) | Un Zarr par simulation (isolation) |
| JSONL de calibration sur disque | Tables `calibration_*` dans DuckDB |
| CSV d'agregation batch | Requetes SQL sur les simulations taguees |
| `geographic_features.geometry_wkb` | Redondant avec `geojson` |
| `results_stable/` | Geographic → DB + memoire |
| `results_simulations/` | `.solver_scratch/` (temp) + DB |
| `results_calibration/` | simulations avec `parent_sim_id` |

## 14. Evolutivite et versioning du schema

### 14.1. Principe

Le schema est concu pour evoluer par **additions**, jamais par modifications destructives.
Les evolutions possibles :
- `CREATE TABLE` : ajouter une table (zero impact sur l'existant)
- `ALTER TABLE ADD COLUMN` : ajouter une colonne (les lignes existantes ont NULL)
- nouvelles valeurs dans les colonnes VARCHAR (solver, param_name, metric_name)
- nouveaux dossiers dans le Zarr (schema-less)

Les evolutions interdites (cassent la compatibilite) :
- renommer ou supprimer une colonne existante
- changer le type d'une colonne
- modifier la cle primaire de `simulations`

### 14.2. Table de version interne

```sql
CREATE TABLE _schema_version (
    version    INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT now()
);
INSERT INTO _schema_version VALUES (1, now());
```

A chaque ouverture de `hydromodpy.duckdb`, le code verifie la version et applique
les migrations necessaires.

### 14.3. Registre de migrations

```python
LATEST_VERSION = 1

MIGRATIONS = {
    # version: liste de statements SQL a executer
    # 1: [],  # schema initial, pas de migration
    # 2: [
    #     "ALTER TABLE simulations ADD COLUMN hmp_version VARCHAR",
    #     "CREATE TABLE sensitivity_indices (...)",
    # ],
    # 3: [
    #     "ALTER TABLE simulations ADD COLUMN mesh_n_nodes INTEGER",
    #     "CREATE TABLE ensemble_runs (...)",
    # ],
}

def ensure_schema(conn: duckdb.DuckDBPyConnection):
    current = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()[0]
    if current >= LATEST_VERSION:
        return
    for v in range(current + 1, LATEST_VERSION + 1):
        for stmt in MIGRATIONS[v]:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO _schema_version VALUES (?, now())", [v]
        )
```

L'historique des migrations est conserve dans `_schema_version` (une ligne par version
appliquee avec timestamp). Permet de savoir quel schema utilise un fichier partage.

### 14.4. Compatibilite import/export

Le package `.hmp` embarque la version du schema :

```python
def export_package(sim_id, output_path):
    # ...
    # copie aussi _schema_version dans le package
    conn.execute("CREATE TABLE _schema_version AS SELECT * FROM src._schema_version")
```

A l'import, si le package a une version plus recente que le workspace :

```python
def import_package(package_path):
    pkg_version = ...  # lire depuis package
    local_version = ... # lire depuis hydromodpy.duckdb
    if pkg_version > local_version:
        raise IncompatibleSchemaError(
            f"Le package utilise le schema v{pkg_version}, "
            f"ce workspace est en v{local_version}. "
            f"Mettez a jour HydroModPy."
        )
    # si pkg_version <= local_version : import normal, les colonnes manquantes = NULL
```

### 14.5. Colonnes cle-valeur : extensibilite sans migration

Les tables `parameters` et `metrics` utilisent un schema **vertical** (cle-valeur).
Ajouter un nouveau parametre ou une nouvelle metrique ne necessite aucune migration :

```
-- Avant (v1) : K et Sy
parameters: (sim_id, 'K', 1.728), (sim_id, 'Sy', 0.05)

-- Apres (v1, aucune migration) : on ajoute porosite et dispersivite
parameters: (sim_id, 'K', 1.728), (sim_id, 'Sy', 0.05),
            (sim_id, 'porosity', 0.15), (sim_id, 'dispersivity', 2.5)
```

Idem pour `metrics` : ajouter KGE', 'pbias', 'volume_error' ne touche pas au schema.

Si un jour on a besoin de metadata sur les noms (unite par defaut, sens de l'optimum),
une table de reference optionnelle peut etre ajoutee :

```sql
-- Migration v2
CREATE TABLE metric_definitions (
    metric_name  VARCHAR PRIMARY KEY,
    display_name VARCHAR,
    direction    VARCHAR,     -- 'higher_is_better' ou 'lower_is_better'
    default_unit VARCHAR
);

INSERT INTO metric_definitions VALUES
    ('nse',   'Nash-Sutcliffe',  'higher_is_better', '-'),
    ('kge',   'Kling-Gupta',     'higher_is_better', '-'),
    ('rmse',  'RMSE',            'lower_is_better',  'm'),
    ('pbias', 'Percent Bias',    'lower_is_better',  '%');
```

`catalog.best()` utilise `direction` pour choisir MAX ou MIN automatiquement.
Les simulations existantes ne sont pas affectees.

### 14.6. JSON blobs : flexibilite vs queryabilite

Certaines colonnes utilisent JSON pour absorber les cas imprevisibles :

| Colonne | Pourquoi JSON | Risque |
|---------|---------------|--------|
| `simulations.config_toml` | snapshot TOML complet, structure variable | trop gros pour normaliser |
| `calibration_iterations.parameters` | N parametres variables par session | nombre de params inconnu a l'avance |
| `calibration_iterations.metrics` | metriques variables par iteration | idem |
| `provenance.stats` | {mean, min, max, std} | schema fixe mais optionnel |
| `geographic_features.properties` | attributs GeoDataFrame variables | depend du jeu de donnees |

Le JSON est queryable en DuckDB via `json_extract()` :

```sql
SELECT json_extract(parameters, '$.K') AS K FROM calibration_iterations;
```

Si le JSON devient un goulot (volume ou performance), la strategie est de **materialiser**
dans une table normalisee sans supprimer le JSON :

```sql
-- Migration vN : materialiser les parametres de calibration
CREATE TABLE calibration_iteration_params (
    session_id UUID,
    iteration  INTEGER,
    param_name VARCHAR,
    value      DOUBLE,
    PRIMARY KEY (session_id, iteration, param_name)
);
-- remplir depuis le JSON existant
INSERT INTO calibration_iteration_params
SELECT session_id, iteration, key, CAST(value AS DOUBLE)
FROM calibration_iterations, json_each(parameters);
```

Le JSON original reste comme archive. La table normalisee sert aux requetes.

### 14.7. Zarr : evolution libre

Zarr est schema-less. Ajouter une variable spatiale = creer un dossier :

```
<uuid>.zarr/
├── head/                    # v1
├── derived/                 # v1
├── velocity/                # v2 : nouveau, aucune migration
└── thermal/                 # v3 : nouveau, aucune migration
```

Les anciennes simulations n'ont pas ces dossiers. Le code verifie la presence
avant de lire :

```python
def field(self, variable, timestep):
    if variable not in self._zarr_root:
        raise VariableNotFound(f"'{variable}' absent de cette simulation")
    return self._zarr_root[variable][timestep][:]
```

Pas de schema a migrer, pas de version a gerer cote Zarr.

### 14.8. Scenarios d'evolution concrets

| Besoin futur | Type de changement | Migration |
|---|---|---|
| Nouveau solver (FEFLOW, PFLOTRAN) | Nouvelle valeur dans `simulations.solver` | Aucune |
| Nouveau process (thermique) | Nouveau dossier Zarr + entrees dans `parameters` | Aucune |
| Version HydroModPy | `ALTER TABLE simulations ADD COLUMN hmp_version VARCHAR` | v2 |
| Ensemble / Monte Carlo | `CREATE TABLE ensemble_runs (ensemble_id, sim_id, weight)` | v2 |
| Scoring multi-objectif | `CREATE TABLE pareto_fronts (front_id, sim_id, rank)` | v2 |
| Metadata utilisateur libre | `ALTER TABLE simulations ADD COLUMN user_metadata JSON` | v2 |
| Spatial indexing (R-tree) | Extension DuckDB `spatial` (pas de DDL) | Aucune |
| Series observees dans la DB | `ALTER TABLE timeseries ADD COLUMN source VARCHAR DEFAULT 'simulated'` | v2 |
| Multi-workspace (cloud) | Le `.hmp` package est deja portable | Aucune |
| Versionning du config TOML | `ALTER TABLE simulations ADD COLUMN schema_version INTEGER DEFAULT 1` | v2 |
| Normaliser les params calibration | `CREATE TABLE calibration_iteration_params (...)` | vN |

Regle : **aucun de ces scenarios ne necessite de reecrire une table existante
ou de modifier des donnees deja stockees.**

### 14.9. Engagement de stabilite

Les elements suivants sont geles et ne changeront pas :

| Element | Garantie |
|---------|----------|
| `simulations.sim_id` (UUID, PK) | Cle universelle, jamais modifiee |
| FK `sim_id` dans toutes les tables | Jointure standard, jamais modifiee |
| Nom du fichier `hydromodpy.duckdb` | Point d'entree unique |
| Structure `simulations/<uuid>.zarr/` | Un Zarr par simulation |
| Noms des tables existantes | Jamais renommees, jamais supprimees |
| Colonnes existantes | Jamais renommees, jamais supprimees |

Tout le reste peut evoluer via le systeme de migrations.

## 15. Requetes SQL de reference

### Lister les simulations d'un bassin

```sql
SELECT sim_id, name, solver, status, duration_s, created_at
FROM simulations
WHERE project = 'canut'
ORDER BY created_at DESC;
```

### Comparer les metriques entre solveurs

```sql
SELECT s.solver, AVG(m.value) AS mean_nse, MIN(m.value), MAX(m.value)
FROM simulations s
JOIN metrics m USING (sim_id)
WHERE s.project = 'canut'
  AND s.status = 'completed'
  AND m.metric_name = 'nse'
GROUP BY s.solver;
```

### Plage de parametres produisant de bons resultats

```sql
SELECT
    ROUND(p.value, 1) AS K_bin,
    COUNT(*) AS n_runs,
    AVG(m.value) AS avg_nse,
    MIN(m.value) AS min_nse,
    MAX(m.value) AS max_nse
FROM parameters p
JOIN metrics m ON p.sim_id = m.sim_id AND m.metric_name = 'nse'
WHERE p.param_name = 'K' AND p.zone_id IS NULL
GROUP BY K_bin
ORDER BY avg_nse DESC;
```

### Comparaison inter-bassins

```sql
SELECT
    s.project,
    p.param_name,
    AVG(p.value) AS mean_value,
    STDDEV(p.value) AS std_value,
    MAX(m.value) AS best_nse
FROM simulations s
JOIN parameters p USING (sim_id)
JOIN metrics m USING (sim_id)
WHERE s.status = 'completed'
  AND m.metric_name = 'nse'
  AND p.zone_id IS NULL
GROUP BY s.project, p.param_name
ORDER BY s.project, p.param_name;
```

### DataFrame ML-ready

```sql
SELECT
    s.sim_id, s.project, s.solver, s.n_cells, s.flow_regime,
    MAX(CASE WHEN p.param_name = 'K'  THEN p.value END) AS K,
    MAX(CASE WHEN p.param_name = 'Sy' THEN p.value END) AS Sy,
    MAX(CASE WHEN p.param_name = 'Ss' THEN p.value END) AS Ss,
    MAX(CASE WHEN m.metric_name = 'nse'  THEN m.value END) AS nse,
    MAX(CASE WHEN m.metric_name = 'kge'  THEN m.value END) AS kge,
    MAX(CASE WHEN m.metric_name = 'rmse' THEN m.value END) AS rmse
FROM simulations s
LEFT JOIN parameters p ON s.sim_id = p.sim_id AND p.zone_id IS NULL
LEFT JOIN metrics m ON s.sim_id = m.sim_id
WHERE s.status = 'completed'
GROUP BY s.sim_id, s.project, s.solver, s.n_cells, s.flow_regime;
```

### Convergence d'une calibration

```sql
SELECT
    iteration,
    objective_value,
    json_extract(parameters, '$.K') AS K,
    json_extract(parameters, '$.Sy') AS Sy
FROM calibration_iterations
WHERE session_id = '<session_id>'
ORDER BY iteration;
```

### Detecter les runs dupliques

```sql
SELECT config_hash, COUNT(*) AS n_duplicates, ARRAY_AGG(sim_id) AS sim_ids
FROM simulations
WHERE status = 'completed'
GROUP BY config_hash
HAVING COUNT(*) > 1;
```
