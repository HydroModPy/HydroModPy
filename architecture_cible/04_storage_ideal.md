# Architecture cible HydroModPy — Stockage des résultats

**Document** : `architecture_cible/04_storage_ideal.md`
**Date** : 2026-04-18
**Auteur** : Architecte data lakehouse / stockage scientifique (références : Pangeo, ESGF, Copernicus CDS, Earthmover Arraylake, Delta Lake, Apache Iceberg).
**Portée** : conception complète du sous-système de stockage de résultats (`hydromodpy/results/`). DuckDB + Zarr + Parquet, UGRID, CF-1.11, format portable `.hmp`.
**Statut attendu** : design de référence — pas un patch incrémental de l'existant.
**Sources** : audit `audit_code/07_results_storage.md`, cibles `01_structure_packages.md` et `03_data_contracts.md`.

> **Légende des tags**
> `[CONSERVE]` existe et est bien · `[REFACTORE]` existe mais doit changer · `[RENOMME]` existe sous un autre nom · `[NOUVEAU]` n'existe pas · `[SUPPRIME]` dead code à retirer

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Panorama du workspace](#1-panorama-du-workspace)
2. [Schéma DuckDB complet](#2-schéma-duckdb-complet)
3. [Layout Zarr v3 CF-UGRID](#3-layout-zarr-v3-cf-ugrid)
4. [Séries ponctuelles en Parquet](#4-séries-ponctuelles-en-parquet)
5. [API Python — SimulationCatalog, Simulation, SimulationGroup](#5-api-python)
6. [Format portable `.hmp`](#6-format-portable-hmp)
7. [Migrations de schéma](#7-migrations-de-schéma)
8. [Concurrence, robustesse, performance](#8-concurrence-robustesse-performance)
9. [Tableau récapitulatif actuel → cible](#9-tableau-récapitulatif-actuel--cible)
10. [Exemples d'usage notebook](#10-exemples-dusage-notebook)

---

## 0. Principes directeurs

| # | Principe | Conséquence pratique |
|---|---|---|
| 1 | **Séparation stricte métadonnées / champs** | DuckDB = métadonnées + timeseries + métriques (SQL). Zarr = champs spatio-temporels N-D. Parquet = chroniques plates lisibles directement par DuckDB/pandas. |
| 2 | **Un seul catalogue par workspace** | `workspace/hydromodpy.duckdb` contient **toutes** les simulations. Le "projet" est une colonne, pas un répertoire. |
| 3 | **Une simulation = un UUID = un `simulations/<uuid>.zarr/`** | Identité forte, déplaçable, hashable. Le Zarr est physiquement isolé, reproductible octet-à-octet. |
| 4 | **Intégrité référentielle SQL** | PK sur toutes les tables, FK `ON DELETE CASCADE` vers `simulations.sim_id`, contraintes `CHECK` sur les énumérations. Plus de cleanup applicatif. |
| 5 | **Typage fort** | `TIMESTAMPTZ` pour tous les instants, `DATE` pour les bornes de période, `DECIMAL(p,s)` pour les flux budget, `UUID` pour les clés. Jamais de `VARCHAR` là où un type natif existe. |
| 6 | **Écriture streaming, schéma idempotent** | `INSERT … ON CONFLICT DO UPDATE` (DuckDB 0.10+). Rejouer un pas de temps écrase, ne duplique pas. Un solveur qui crash à t=37 peut reprendre à t=37. |
| 7 | **Métadonnées CF-1.11 + UGRID-1.0 dans le Zarr** | Zéro attribut dans DuckDB qui ne soit dans le Zarr. Le Zarr est **auto-descriptif** : `xarray.open_zarr(...)` suffit pour la science. |
| 8 | **Unification DIS / DISV / DISU via UGRID** | La dimension métier est `face`, jamais `row/col/node`. Un helper `mesh.face_to_row_col()` existe pour la régulière seulement. |
| 9 | **Migrations ordonnées, testées, réversibles** | `_schema_version` + liste `MIGRATIONS` + test de round-trip v(n) → v(n+1) → v(n). |
| 10 | **Format portable auto-décrit et versionné** | `.hmp` = `tar.zst` avec `manifest.json`. `format_version` indépendant de `schema_version`. Round-trip export→import testé. |
| 11 | **Single-writer + lock explicite** | `filelock` sur `hydromodpy.duckdb.lock`. Double lancement = erreur claire, pas deadlock DuckDB. |
| 12 | **Provenance scientifique PROV-O complète** | Table `runs_environment` (user, host, git_sha, python_ver, solver_binary_sha). SHA-256 sur fichier **source**, pas sur `tobytes()`. |

### 0.1 Comparaison aux projets de référence

| Projet | Ce qu'il fait bien | Ce qu'on reprend | Ce qu'on ne reprend pas |
|---|---|---|---|
| **Pangeo** | Zarr + dask + xarray + intake | Zarr v3 CF, chunking balanced, consolidated metadata | Pas d'Intake catalog YAML (DuckDB + `catalog.find()` plus simple) |
| **ESGF / CMIP6** | DRS (Data Reference Syntax) : hiérarchie `project/model/variant/realm/var/...` | Rien. Notre `project` est un label DuckDB, pas un dossier. | Arbre de dossiers rigide → ingérable pour 10 000 sims |
| **Copernicus CDS** | Catalog API + bundles NetCDF CF | `to_xarray()` auto-CF, exports NetCDF CF-1.11 | Pas de couche API HTTP |
| **Earthmover Arraylake** | Branching / versioning Zarr via DuckDB | Métadonnées DuckDB unique, Zarr per-array | Pas de versioning git-like (over-engineering pour notre cible) |
| **Delta Lake / Iceberg** | Transactions ACID, time-travel, schema evolution | Migrations versionnées, UPSERT, snapshot isolation via DuckDB | Pas de time-travel (les sims sont append-only, un rerun = nouvel UUID) |
| **HDF5 / NetCDF classique** | Un fichier = un dataset, portable | UGRID CF layout compatible lecture NetCDF export | Pas d'écriture concurrente, ne scale pas au cloud |
| **STAC 1.0** | Catalog d'items raster standardisé | `.hmp` ressemble conceptuellement à un Item STAC | Pas de JSON-LD strict, pas de "Collections" (surcharge inutile) |
| **RO-Crate** | Research Object Crate JSON-LD | `manifest.json` auto-décrit | Pas de full RO-Crate (JSON plat suffit) |
| **MLflow Tracking** | params + metrics + artifacts | `parameters`/`metrics` idem ; `to_dataframe(params=…, metrics=…)` | Pas de UI Flask, pas de client REST |

---

## 1. Panorama du workspace

### 1.1 Layout physique

```
workspace/                                    # racine utilisateur (créée par `hmp init`)
│
├── hydromodpy.duckdb                         # 1 fichier, catalog UNIQUE pour tous les projets
├── hydromodpy.duckdb.wal                     # WAL DuckDB (géré nativement)
├── hydromodpy.duckdb.lock                    # filelock sentinelle (single-writer)
│
├── configs/                                  # TOML utilisateur (organisation libre)
│   ├── canut/
│   │   ├── baseline.toml
│   │   └── calibration.toml
│   └── brittany/
│
├── data/                                     # CACHE d'entrée (voir doc 03)
│   ├── cache.duckdb
│   ├── cache.duckdb.lock
│   └── <variable>/                           # fichiers pivots (Parquet, GeoParquet, COG)
│
├── simulations/                              # UN dossier Zarr par simulation (UUID)
│   ├── 0a1f9c3d-8e2b-4a7f-bd92-…..zarr/      # directory store (en cours)
│   ├── 2b4c1e6a-…..zarr.zip                  # ZipStore après `finalize()` (immuable)
│   └── 3f7d2a8e-…..zarr/
│
├── exports/                                  # Paquets portables partageables
│   ├── canut-baseline-2026-04-18.hmp
│   └── brittany-best.hmp
│
└── logs/                                     # Logs runtime (optionnel)
    └── <run_id>.log
```

**Règles invariantes** :

- Le workspace est **mono-writer** (lock). Tout processus `hmp run` s'enregistre dans `hydromodpy.duckdb.lock`, sinon lève `WorkspaceLockedError`.
- Un `simulations/<uuid>.zarr/` est **auto-suffisant** : il peut être copié vers un autre workspace, re-catalogué via `import_simulation()`.
- `hydromodpy.duckdb` ne contient **jamais** de chemins absolus. Tous les `zarr_path` sont **relatifs au workspace**.
- Aucun fichier dans `configs/` n'est lu par le runtime une fois la simulation lancée — le TOML est cloné dans `simulations.config_toml` (JSON) et optionnellement dans le Zarr (`.zattrs["config_toml"]`).

### 1.2 Trois tiers de données

| Tier | Technologie | Contenu | Taille typique | Accès prioritaire |
|---|---|---|---|---|
| **Hot metadata** | DuckDB | 16 tables normalisées : sims, params, metrics, timeseries, budgets, provenance, calib, geographic | 10 MB – 1 GB | SQL (pandas, `catalog.sql()`) |
| **Warm fields** | Zarr v3 | Champs (time, layer, face) : head, drawdown, budget spatial, pathlines, derived, geographic rasters | 100 MB – 100 GB par sim | `xarray.open_zarr()` |
| **Cold tabular** | Parquet (dans le Zarr) | Chroniques ponctuelles, stations GeoParquet, vecteurs géographiques | 1 – 100 MB par sim | `duckdb.read_parquet()`, `geopandas.read_parquet()` |

Le **tier hot** est dupliqué **minimalement** depuis le Zarr (pour permettre le SQL rapide). Toute valeur présente en DuckDB existe aussi en source-of-truth dans le Zarr ou dans le TOML versionné dans `simulations.config_toml`.

---

## 2. Schéma DuckDB complet

### 2.1 Vue d'ensemble

**16 tables + 4 vues**. Arborescence référentielle :

```
                                   _schema_version  (1 ligne par version appliquée)
                                   ─────────────────
                                           │
┌─────────────────────────────────┐        │
│  simulations  (racine — 1 run)  │◄───────┴──── FK ON DELETE CASCADE
└─────────────────────────────────┘               sur toutes les tables per-sim
        ▲                                         (9 tables ci-dessous)
        │ parent_sim_id (self-FK, ON DELETE SET NULL)
        │
   ┌────┴────┬─────────────┬──────────────┬────────────────┬─────────────┐
   │         │             │              │                │             │
parameters  metrics    timeseries      budgets         mass_balance   provenance
(idempot.)  (idempot.) (streaming)     (streaming)    (1/timestep)    (lineage)

   ┌─────────────────────┬──────────────────┬────────────────────────┐
   │                     │                  │                        │
runs_environment    observation_points  geographic_features    geographic_metadata
(1 ligne/sim)       (station→cell)      (vecteurs: watershed…)  (KV scalaires)
[NOUVEAU]

calibration_sessions  ──────────────┐
(session_id PK)                     │
        ▲ session_id FK             │ best_sim_id FK (ON DELETE SET NULL)
        │                           ▼
calibration_iterations         simulations
(session_id, iteration)

stations               tags
[NOUVEAU]              [NOUVEAU, normalisé]
(indep. de sim_id)     (sim_id, tag)
```

### 2.2 DDL complet

```sql
-- ========================================================================
--  HydroModPy Simulation Catalog — Schema v1
--  File: hydromodpy/results/schema/tables.py  → executed by migrations.py
-- ========================================================================

PRAGMA enable_checkpoint_on_shutdown;
INSTALL spatial;                       -- pour GEOMETRY et RTREE (optionnel)
LOAD spatial;

-- ------------------------------------------------------------------------
-- 0. _schema_version : versioning des migrations
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS _schema_version (
    version      INTEGER   PRIMARY KEY,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    description  VARCHAR   NOT NULL,
    hmp_version  VARCHAR   NOT NULL
);

-- ------------------------------------------------------------------------
-- 1. simulations : table racine. Une ligne = un run identifié par UUID.
-- ------------------------------------------------------------------------
CREATE TYPE sim_status AS ENUM ('pending', 'running', 'completed', 'failed', 'aborted');
CREATE TYPE flow_regime AS ENUM ('steady', 'transient', 'steady_then_transient');
CREATE TYPE mesh_topology AS ENUM ('dis', 'disv', 'disu');
CREATE TYPE solver_category AS ENUM ('modflow', 'boussinesq', 'gr4j', 'hybrid');

CREATE TABLE IF NOT EXISTS simulations (
    sim_id          UUID         PRIMARY KEY DEFAULT uuid(),
    name            VARCHAR,
    project         VARCHAR      NOT NULL,               -- label libre, indexé
    solver          VARCHAR      NOT NULL,               -- 'modflow6', 'modflownwt', …
    solver_category solver_category NOT NULL,            -- dérivé mais persisté pour GROUP BY
    flow_regime     flow_regime  NOT NULL,
    status          sim_status   NOT NULL DEFAULT 'pending',

    -- Dimensions spatio-temporelles (source de vérité : Zarr .zattrs)
    n_cells         INTEGER      NOT NULL CHECK (n_cells > 0),
    n_layers        INTEGER      NOT NULL CHECK (n_layers > 0),
    n_timesteps     INTEGER      CHECK (n_timesteps >= 0),
    mesh_topology   mesh_topology NOT NULL,
    mesh_hash       VARCHAR(64)  NOT NULL,               -- SHA-256 du mesh (reuse detection)
    crs_wkt         VARCHAR      NOT NULL,               -- WKT2 complet, pas 'EPSG:2154'
    crs_epsg        INTEGER,                             -- dénormalisé pour requête humaine

    -- Bornes spatiales (cohérentes avec le mesh)
    bbox_xmin       DOUBLE NOT NULL,
    bbox_ymin       DOUBLE NOT NULL,
    bbox_xmax       DOUBLE NOT NULL,
    bbox_ymax       DOUBLE NOT NULL,
    CHECK (bbox_xmax > bbox_xmin AND bbox_ymax > bbox_ymin),

    -- Bornes temporelles (TIMESTAMPTZ — jamais VARCHAR)
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    time_unit       VARCHAR NOT NULL DEFAULT 'day',      -- CF units
    CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start),

    -- Configuration complète (source de vérité pour reproductibilité)
    config_toml     JSON         NOT NULL,               -- full HydroModPyConfig
    config_hash     VARCHAR(64)  NOT NULL,               -- SHA-256 du TOML canonique
    config_schema_version INTEGER NOT NULL,              -- version Pydantic aggregate

    -- Lineage
    parent_sim_id   UUID         REFERENCES simulations(sim_id) ON DELETE SET NULL,
    lineage_kind    VARCHAR,                             -- 'rerun', 'fork', 'calibration_member'

    -- Pointeur physique (relatif au workspace !)
    zarr_path       VARCHAR      NOT NULL,               -- ex: 'simulations/<uuid>.zarr'
    zarr_packed     BOOLEAN      NOT NULL DEFAULT FALSE, -- TRUE si .zarr.zip (finalisé)

    -- Runtime
    duration_s      DOUBLE,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT current_timestamp,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT current_timestamp,

    -- Notes utilisateur
    notes           VARCHAR
);

CREATE INDEX ix_sim_project         ON simulations(project);
CREATE INDEX ix_sim_solver          ON simulations(solver);
CREATE INDEX ix_sim_status          ON simulations(status);
CREATE INDEX ix_sim_created_at      ON simulations(created_at DESC);
CREATE INDEX ix_sim_parent          ON simulations(parent_sim_id);
CREATE INDEX ix_sim_config_hash     ON simulations(config_hash);  -- dedupe
CREATE INDEX ix_sim_mesh_hash       ON simulations(mesh_hash);
CREATE INDEX ix_sim_bbox            ON simulations USING RTREE(bbox_xmin, bbox_ymin,
                                                               bbox_xmax, bbox_ymax);

-- ------------------------------------------------------------------------
-- 2. runs_environment [NOUVEAU] : provenance scientifique PROV-O complète
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs_environment (
    sim_id           UUID PRIMARY KEY REFERENCES simulations(sim_id) ON DELETE CASCADE,
    run_id           UUID NOT NULL,                      -- UUID du process (= job_id si HPC)
    user_login       VARCHAR NOT NULL,
    hostname         VARCHAR NOT NULL,
    os_name          VARCHAR NOT NULL,                   -- 'Linux-6.19-fc43'
    python_version   VARCHAR NOT NULL,
    hmp_version      VARCHAR NOT NULL,                   -- semver ou git sha
    git_sha          VARCHAR(40),                        -- git rev-parse HEAD
    git_dirty        BOOLEAN NOT NULL DEFAULT FALSE,     -- uncommitted changes?
    solver_binary    VARCHAR,                            -- chemin exe
    solver_binary_sha VARCHAR(64),                       -- SHA-256 du binaire solveur
    solver_version   VARCHAR,                            -- stdout --version
    cpu_count        INTEGER,
    ram_gb           DOUBLE,
    pip_freeze       JSON,                               -- snapshot env
    env_vars         JSON,                               -- HMP_* filtrés
    started_at       TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ
);

CREATE INDEX ix_runenv_user ON runs_environment(user_login);
CREATE INDEX ix_runenv_host ON runs_environment(hostname);

-- ------------------------------------------------------------------------
-- 3. parameters : hyperparamètres effectifs du run (K, Sy, drainage…)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parameters (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    param_name      VARCHAR NOT NULL,                    -- 'K', 'Sy', 'drn_cond'
    zone_id         VARCHAR NOT NULL DEFAULT '__global__',
    value           DOUBLE  NOT NULL,
    unit            VARCHAR NOT NULL,                    -- CF units ('m/s', 'm3/s/m', '1')
    parameterization VARCHAR NOT NULL DEFAULT 'uniform', -- 'uniform', 'zonal', 'pilot_points'
    PRIMARY KEY (sim_id, param_name, zone_id)
);

CREATE INDEX ix_param_name ON parameters(param_name);

-- ------------------------------------------------------------------------
-- 4. metrics : scores de performance (NSE, KGE, RMSE, …)
-- ------------------------------------------------------------------------
CREATE TYPE metric_name AS ENUM
  ('nse', 'kge', 'kge_prime', 'rmse', 'mae', 'r2', 'pbias', 'vol_error',
   'nse_log', 'nse_sqrt', 'mare', 'custom');

CREATE TABLE IF NOT EXISTS metrics (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    station_id      VARCHAR NOT NULL DEFAULT '__outlet__',
    variable        VARCHAR NOT NULL,                    -- 'head', 'discharge', 'concentration'
    metric_name     metric_name NOT NULL,
    value           DOUBLE,                              -- nullable : NaN autorisé
    n_samples       INTEGER,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    PRIMARY KEY (sim_id, station_id, variable, metric_name)
);

CREATE INDEX ix_metrics_metric ON metrics(metric_name, value);

-- ------------------------------------------------------------------------
-- 5. timeseries : séries simulées (head, débit, concentration aux stations)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS timeseries (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    station_id      VARCHAR NOT NULL,
    variable        VARCHAR NOT NULL,
    datetime        TIMESTAMPTZ NOT NULL,
    value           DOUBLE,                              -- NULL permis (NaN hydro)
    unit            VARCHAR NOT NULL,
    qflag           VARCHAR DEFAULT 'simulated',         -- 'simulated', 'gap', 'spinup'
    PRIMARY KEY (sim_id, station_id, variable, datetime)
);

-- Lookup principal pour pivot/compare
CREATE INDEX ix_ts_lookup ON timeseries(sim_id, station_id, variable, datetime);
-- Lookup transversal pour comparaison multi-sim (catalog.compare_station)
CREATE INDEX ix_ts_cross_sim ON timeseries(station_id, variable, datetime);

-- ------------------------------------------------------------------------
-- 6. budgets : bilans zonaux par timestep et composante
-- ------------------------------------------------------------------------
CREATE TYPE budget_component AS ENUM
  ('recharge', 'drain', 'river', 'ghb', 'chd', 'well', 'storage',
   'constant_head', 'specified_flow', 'evapotranspiration', 'seepage');

CREATE TABLE IF NOT EXISTS budgets (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    timestep        INTEGER NOT NULL CHECK (timestep >= 0),
    zone_id         VARCHAR NOT NULL DEFAULT '__global__',
    component       budget_component NOT NULL,
    flux_in         DOUBLE NOT NULL DEFAULT 0.0,
    flux_out        DOUBLE NOT NULL DEFAULT 0.0,
    unit            VARCHAR NOT NULL DEFAULT 'm3/d',
    PRIMARY KEY (sim_id, timestep, zone_id, component)
);

CREATE INDEX ix_budgets_component ON budgets(component);

-- ------------------------------------------------------------------------
-- 7. mass_balance : bilan global par timestep
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mass_balance (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    timestep        INTEGER NOT NULL,
    total_in        DOUBLE NOT NULL,
    total_out       DOUBLE NOT NULL,
    storage_in      DOUBLE NOT NULL,
    storage_out     DOUBLE NOT NULL,
    percent_error   DOUBLE NOT NULL,
    unit            VARCHAR NOT NULL DEFAULT 'm3/d',
    PRIMARY KEY (sim_id, timestep)
);

-- ------------------------------------------------------------------------
-- 8. observation_points : station → cellule de maillage
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observation_points (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    station_id      VARCHAR NOT NULL,
    x               DOUBLE NOT NULL,
    y               DOUBLE NOT NULL,
    cell_id         INTEGER NOT NULL,                    -- face id dans le mesh UGRID
    layer           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sim_id, station_id)
);

CREATE INDEX ix_obs_cell ON observation_points(sim_id, cell_id);

-- ------------------------------------------------------------------------
-- 9. provenance : lineage des données d'entrée (PROV-O Entity)
-- ------------------------------------------------------------------------
CREATE TYPE source_type AS ENUM ('http_api', 'custom_file', 'derived', 'cache');

CREATE TABLE IF NOT EXISTS provenance (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    variable        VARCHAR NOT NULL,
    source_type     source_type NOT NULL,
    source_ref      VARCHAR NOT NULL,                    -- URI / chemin / UUID artefact
    source_sha256   VARCHAR(64),                         -- hash du FICHIER source (pas tobytes)
    payload_sha256  VARCHAR(64),                         -- hash de l'array ingéré (post-parse)
    loader_name     VARCHAR NOT NULL,
    loader_version  VARCHAR NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    n_records       BIGINT,                              -- lignes pour chronique, cells pour raster
    stats           JSON,                                -- {min,max,mean,std,n_nan}
    PRIMARY KEY (sim_id, variable, source_ref)
);

CREATE INDEX ix_prov_sha ON provenance(source_sha256);

-- ------------------------------------------------------------------------
-- 10. calibration_sessions : session de calibration (parent de N sims)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration_sessions (
    session_id      UUID PRIMARY KEY DEFAULT uuid(),
    project         VARCHAR NOT NULL,
    method          VARCHAR NOT NULL,                    -- 'latin_hypercube', 'dream', 'pest'
    objective_name  VARCHAR NOT NULL,                    -- 'nse', 'composite_nse_kge'
    n_iterations    INTEGER NOT NULL,
    best_sim_id     UUID REFERENCES simulations(sim_id) ON DELETE SET NULL,
    best_objective  DOUBLE,
    config          JSON NOT NULL,                       -- [calibration] TOML section
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    duration_s      DOUBLE,
    status          sim_status NOT NULL DEFAULT 'pending'
);

CREATE INDEX ix_cal_project ON calibration_sessions(project);

-- ------------------------------------------------------------------------
-- 11. calibration_iterations : trace d'itération (parameters, objective)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration_iterations (
    session_id      UUID REFERENCES calibration_sessions(session_id) ON DELETE CASCADE,
    iteration       INTEGER NOT NULL,
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE SET NULL,
    parameters      JSON NOT NULL,                       -- {K: 1.5e-5, Sy: 0.12}
    objective_value DOUBLE,
    metrics         JSON,                                -- {nse: 0.87, kge: 0.73}
    duration_s      DOUBLE,
    PRIMARY KEY (session_id, iteration)
);

CREATE INDEX ix_cal_iter_sim ON calibration_iterations(sim_id);

-- ------------------------------------------------------------------------
-- 12. geographic_features : vecteurs par simulation (watershed, rivières)
-- ------------------------------------------------------------------------
CREATE TYPE geometry_kind AS ENUM ('point', 'linestring', 'polygon', 'multipolygon');

CREATE TABLE IF NOT EXISTS geographic_features (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    feature_name    VARCHAR NOT NULL,                    -- 'watershed', 'rivers', 'drains'
    geometry_kind   geometry_kind NOT NULL,
    crs_wkt         VARCHAR NOT NULL,
    geoparquet_path VARCHAR,                             -- relatif au Zarr : 'geographic/watershed.parquet'
    properties      JSON,                                -- propriétés de la feature
    PRIMARY KEY (sim_id, feature_name)
);

-- ------------------------------------------------------------------------
-- 13. geographic_metadata : métadonnées scalaires (catch_area, dem_res, …)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geographic_metadata (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    key             VARCHAR NOT NULL,                    -- 'catch_area_km2', 'dem_resolution_m'
    value           VARCHAR NOT NULL,                    -- stocké en string, cast à la lecture
    value_type      VARCHAR NOT NULL DEFAULT 'string',   -- 'double', 'int', 'string', 'bool'
    unit            VARCHAR,
    PRIMARY KEY (sim_id, key)
);

-- ------------------------------------------------------------------------
-- 14. stations [NOUVEAU] : collection de points d'observation (indépendant des sims)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stations (
    station_id      VARCHAR NOT NULL,
    provider        VARCHAR NOT NULL DEFAULT 'custom',   -- 'hubeau', 'ades', 'shom', 'custom'
    variable        VARCHAR NOT NULL,
    name            VARCHAR,
    x               DOUBLE NOT NULL,
    y               DOUBLE NOT NULL,
    crs_epsg        INTEGER NOT NULL,
    altitude_m      DOUBLE,
    metadata        JSON,
    PRIMARY KEY (station_id, provider, variable)
);

-- Miroir indexable depuis workspace/data/cache.duckdb via ATTACH.
-- Peut être synchronisé à la volée ; ici c'est une matérialisation pour requête rapide.

-- ------------------------------------------------------------------------
-- 15. tags [NOUVEAU] : tags normalisés (remplace simulations.tags VARCHAR[])
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tags (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    tag             VARCHAR NOT NULL,
    PRIMARY KEY (sim_id, tag)
);

CREATE INDEX ix_tags_tag ON tags(tag);

-- ------------------------------------------------------------------------
-- 16. observations [NOUVEAU] : observations terrain pour calage (DRY from cache)
-- ------------------------------------------------------------------------
-- Matérialisation (ou vue) des chroniques observées utilisées pour le calage.
-- Permet des JOIN simulé/observé sans lire Parquet externe.
CREATE TABLE IF NOT EXISTS observations (
    sim_id          UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    station_id      VARCHAR NOT NULL,
    variable        VARCHAR NOT NULL,
    datetime        TIMESTAMPTZ NOT NULL,
    value           DOUBLE,
    unit            VARCHAR NOT NULL,
    qflag           VARCHAR,
    source_artifact_id UUID,                             -- FK logique vers cache.artifacts
    PRIMARY KEY (sim_id, station_id, variable, datetime)
);

CREATE INDEX ix_obs_lookup ON observations(sim_id, station_id, variable, datetime);
```

### 2.3 Vues dénormalisées (convenience)

```sql
-- ------------------------------------------------------------------------
-- v_simulation_summary : simulation + métriques clés + durée
-- ------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_simulation_summary AS
SELECT
    s.sim_id, s.name, s.project, s.solver, s.status,
    s.flow_regime, s.n_cells, s.n_layers, s.n_timesteps,
    s.period_start, s.period_end,
    s.duration_s, s.created_at,
    m_nse.value   AS nse_outlet,
    m_kge.value   AS kge_outlet,
    m_rmse.value  AS rmse_outlet,
    mb.percent_error_max,
    re.user_login, re.hmp_version, re.git_sha,
    COUNT_IF(t.tag IS NOT NULL) OVER (PARTITION BY s.sim_id) AS n_tags
FROM simulations s
LEFT JOIN metrics m_nse
    ON s.sim_id = m_nse.sim_id AND m_nse.station_id = '__outlet__'
    AND m_nse.variable = 'discharge' AND m_nse.metric_name = 'nse'
LEFT JOIN metrics m_kge
    ON s.sim_id = m_kge.sim_id AND m_kge.station_id = '__outlet__'
    AND m_kge.variable = 'discharge' AND m_kge.metric_name = 'kge'
LEFT JOIN metrics m_rmse
    ON s.sim_id = m_rmse.sim_id AND m_rmse.station_id = '__outlet__'
    AND m_rmse.variable = 'discharge' AND m_rmse.metric_name = 'rmse'
LEFT JOIN (
    SELECT sim_id, MAX(ABS(percent_error)) AS percent_error_max
    FROM mass_balance GROUP BY sim_id
) mb ON s.sim_id = mb.sim_id
LEFT JOIN runs_environment re ON s.sim_id = re.sim_id
LEFT JOIN tags t ON s.sim_id = t.sim_id;

-- ------------------------------------------------------------------------
-- v_best_per_project : meilleure sim NSE par projet
-- ------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_best_per_project AS
SELECT *
FROM v_simulation_summary
QUALIFY ROW_NUMBER() OVER (PARTITION BY project ORDER BY nse_outlet DESC NULLS LAST) = 1;

-- ------------------------------------------------------------------------
-- v_params_wide : pivot des paramètres pour ML (sim_id × param_name)
-- ------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_params_wide AS
PIVOT parameters ON param_name USING MAX(value) GROUP BY sim_id, zone_id;

-- ------------------------------------------------------------------------
-- v_metrics_wide : pivot des métriques pour ML (sim_id × metric_name)
-- ------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_metrics_wide AS
PIVOT metrics ON metric_name USING MAX(value)
GROUP BY sim_id, station_id, variable;

-- ------------------------------------------------------------------------
-- v_simulation_inputs_provenance : join cross-DB avec le cache d'entrée
-- ------------------------------------------------------------------------
-- Nécessite ATTACH 'data/cache.duckdb' AS cache_db (READ_ONLY).
CREATE OR REPLACE VIEW v_simulation_inputs_provenance AS
SELECT
    s.sim_id, s.project,
    p.variable, p.source_type, p.source_ref,
    p.source_sha256, p.fetched_at,
    art.provider, art.path, art.status AS cache_status
FROM simulations s
JOIN provenance p USING (sim_id)
LEFT JOIN cache_db.cache.artifacts art ON p.source_sha256 = art.sha256;
```

### 2.4 Requêtes SQL pour cas d'usage typiques

**1) Meilleure simulation par NSE pour un projet**

```sql
SELECT sim_id, name, nse_outlet, kge_outlet, created_at
FROM v_simulation_summary
WHERE project = 'canut' AND status = 'completed'
ORDER BY nse_outlet DESC NULLS LAST
LIMIT 1;
```

**2) Comparer K et NSE sur 200 simulations d'une session de calibration**

```sql
SELECT
    p.value AS K,
    m.value AS nse,
    s.sim_id
FROM simulations s
JOIN parameters p ON s.sim_id = p.sim_id
    AND p.param_name = 'K' AND p.zone_id = '__global__'
JOIN metrics m    ON s.sim_id = m.sim_id
    AND m.station_id = '__outlet__' AND m.variable = 'discharge'
    AND m.metric_name = 'nse'
JOIN calibration_iterations ci ON ci.sim_id = s.sim_id
WHERE ci.session_id = '…'
ORDER BY K;
```

**3) Exporter la chronique simulée d'une station en CSV**

```sql
COPY (
  SELECT datetime, value, unit
  FROM timeseries
  WHERE sim_id = '…' AND station_id = 'P01' AND variable = 'head'
  ORDER BY datetime
) TO 'P01_head.csv' (HEADER, DELIMITER ',', DATEFORMAT '%Y-%m-%d');
```

**4) Dataset ML prêt : (params, metrics) joints en DataFrame large**

```sql
-- SQL :
SELECT pw.sim_id, pw.K, pw.Sy, pw.drn_cond,
       mw.nse, mw.kge, mw.rmse,
       s.n_cells, s.mesh_topology
FROM v_params_wide pw
JOIN v_metrics_wide mw
  ON pw.sim_id = mw.sim_id
 AND mw.station_id = '__outlet__' AND mw.variable = 'discharge'
JOIN simulations s ON s.sim_id = pw.sim_id
WHERE s.project = 'canut' AND s.status = 'completed';
```

**5) Détecter les simulations avec doublons de config (dédup via config_hash)**

```sql
SELECT config_hash, ARRAY_AGG(sim_id) AS sims, COUNT(*) AS n
FROM simulations
GROUP BY config_hash
HAVING COUNT(*) > 1;
```

**6) Comparaison multi-sims sur une même station (crossplot simulé/observé)**

```sql
SELECT t.sim_id, t.datetime, t.value AS simulated, o.value AS observed
FROM timeseries t
LEFT JOIN observations o
  ON t.sim_id = o.sim_id
 AND t.station_id = o.station_id
 AND t.variable = o.variable
 AND t.datetime = o.datetime
WHERE t.sim_id IN (…)
  AND t.station_id = 'P01' AND t.variable = 'head';
```

**7) Trouver toutes les sims qui utilisent un fichier d'entrée précis (pour purge)**

```sql
SELECT DISTINCT s.sim_id, s.project
FROM simulations s
JOIN provenance p USING (sim_id)
WHERE p.source_sha256 = 'a3f7…';
```

### 2.5 Mécanisme de migration

Code type `hydromodpy/results/catalog/migrations.py` `[NOUVEAU]` :

```python
# hydromodpy/results/catalog/migrations.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import duckdb
from importlib.metadata import version as _pkg_version

SCHEMA_VERSION = 3   # version cible actuelle


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    up: Callable[[duckdb.DuckDBPyConnection], None]
    down: Callable[[duckdb.DuckDBPyConnection], None] | None = None


# --- v1 : initial schema -------------------------------------------------
def _up_v1(conn):
    conn.execute(_INITIAL_SCHEMA_SQL)   # DDL complet (voir §2.2)


# --- v2 : add runs_environment + source_sha256 ---------------------------
def _up_v2(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs_environment (...);
        ALTER TABLE provenance ADD COLUMN IF NOT EXISTS source_sha256 VARCHAR(64);
        ALTER TABLE provenance ADD COLUMN IF NOT EXISTS payload_sha256 VARCHAR(64);
    """)


def _down_v2(conn):
    conn.execute("""
        DROP TABLE IF EXISTS runs_environment;
        ALTER TABLE provenance DROP COLUMN IF EXISTS source_sha256;
        ALTER TABLE provenance DROP COLUMN IF EXISTS payload_sha256;
    """)


# --- v3 : normalize tags + add stations ---------------------------------
def _up_v3(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (sim_id UUID, tag VARCHAR, ...);
        INSERT INTO tags (sim_id, tag)
            SELECT sim_id, UNNEST(tags) FROM simulations WHERE tags IS NOT NULL;
        ALTER TABLE simulations DROP COLUMN tags;

        CREATE TABLE IF NOT EXISTS stations (...);
    """)


MIGRATIONS: list[Migration] = [
    Migration(1, "initial schema", _up_v1),
    Migration(2, "runs_environment + source_sha256", _up_v2, _down_v2),
    Migration(3, "tags table + stations", _up_v3),
]


def migrate(conn: duckdb.DuckDBPyConnection, *, target: int | None = None) -> int:
    """Upgrade DuckDB schema to target (or latest). Returns final version."""
    target = target or SCHEMA_VERSION
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
            description VARCHAR NOT NULL,
            hmp_version VARCHAR NOT NULL
        )
    """)
    current = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM _schema_version"
    ).fetchone()[0]

    for mig in MIGRATIONS:
        if mig.version <= current or mig.version > target:
            continue
        conn.begin()
        try:
            mig.up(conn)
            conn.execute(
                "INSERT INTO _schema_version VALUES (?, current_timestamp, ?, ?)",
                [mig.version, mig.description, _pkg_version("hydromodpy")],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return conn.execute(
        "SELECT MAX(version) FROM _schema_version"
    ).fetchone()[0]
```

**Test obligatoire** `tests/unit/results/test_migrations.py` :

```python
def test_migration_v1_to_v3(tmp_path):
    # Charge un snapshot v1 versionné dans tests/fixtures/schema_v1.duckdb
    shutil.copy(FIXTURE_V1, tmp_path / "hydromodpy.duckdb")
    conn = duckdb.connect(str(tmp_path / "hydromodpy.duckdb"))
    assert migrate(conn) == 3
    # Vérifier que toutes les sims sont préservées
    assert conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0] == EXPECTED
    # Vérifier que les tags ont migré
    assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] > 0
```

---

## 3. Layout Zarr v3 CF-UGRID

### 3.1 Structure détaillée

```
simulations/<uuid>.zarr/                 # directory store (en cours)
│                                        # OU <uuid>.zarr.zip (finalisé, ZipStore read-only)
├── zarr.json                            # manifest Zarr v3 racine
├── .zattrs (root)                       # voir §3.2
│
├── mesh/                                # UGRID 1.0 — unique pour DIS/DISV/DISU
│   ├── node_x                 (n_node,)          float64, units="m"
│   ├── node_y                 (n_node,)          float64, units="m"
│   ├── node_z                 (n_node,) optional float64, units="m"
│   ├── face_x                 (n_face,)          float64, centroids
│   ├── face_y                 (n_face,)          float64
│   ├── face_node_connectivity (n_face, max_vpf)  int32, _FillValue=-1
│   ├── edge_node_connectivity (n_edge, 2)        int32, optional
│   ├── z_interfaces           (n_layers+1, n_face) float64
│   ├── surface_top            (n_face,)          float64
│   ├── surface_bottom         (n_face,)          float64
│   └── mesh (scalar DataArray with cf_role=mesh_topology)
│
├── time                       (n_timesteps,) int64
│                              units="days since YYYY-MM-DD", calendar="standard"
├── layer                      (n_layers,)    int16
│                              long_name="layer_index"
│
├── head                       (n_t, n_layers, n_face) float32
├── drawdown                   (n_t, n_layers, n_face) float32
├── concentration              (n_t, n_layers, n_face) float32   (si transport)
│
├── derived/
│   ├── watertable_elevation   (n_t, n_face)  float32
│   ├── watertable_depth       (n_t, n_face)  float32
│   └── seepage_mask           (n_t, n_face)  uint8              (RLE-friendly)
│
├── budget/                                                      # champs spatiaux de flux
│   ├── recharge               (n_t, n_layers, n_face) float32, units="m s-1"
│   ├── drain                  (n_t, n_layers, n_face) float32
│   ├── river                  (n_t, n_layers, n_face) float32
│   ├── storage                (n_t, n_layers, n_face) float32
│   └── well                   (n_t, n_layers, n_face) float32
│
├── pathlines/                                                   # MODPATH (groupe optionnel)
│   ├── particle_id            (n_particles,) int64
│   ├── x, y, z, time          (n_particles, max_steps) float32
│   └── zone_start, zone_end   (n_particles,) int32
│
├── geographic/                                                  # rasters statiques
│   ├── dem                    (ny, nx) float32, grid_mapping="crs"
│   ├── geology                (ny, nx) uint16 + .zattrs.lithology_lookup JSON
│   ├── watershed.parquet                                        # GeoParquet direct
│   └── rivers.parquet                                           # GeoParquet direct
│
├── timeseries/                                                  # chroniques ponctuelles
│   ├── observations.parquet                                     # long format (§4)
│   ├── simulated.parquet                                        # long format (§4)
│   └── stations.geoparquet
│
└── crs                        (scalar)
                                grid_mapping_name="lambert_conformal_conic"
                                crs_wkt="..."
                                epsg_code=2154
```

### 3.2 Attributs `.zattrs` au niveau racine

```json
{
  "Conventions": "CF-1.11 UGRID-1.0",
  "title": "HydroModPy simulation canut/baseline (2020-2022)",
  "institution": "LabX / University Y",
  "source": "HydroModPy 0.4.2+g74b62878",
  "history": "2026-04-18T14:22:00Z: created",
  "references": "https://hydromodpy.readthedocs.io/spec/v1",
  "sim_id": "0a1f9c3d-8e2b-4a7f-bd92-…",
  "hmp_version": "0.4.2",
  "hmp_git_sha": "74b62878",
  "schema_version": 1,
  "zarr_format": 3,
  "created_at": "2026-04-18T14:22:00Z",
  "config_toml": "<full TOML as JSON-encoded string>",
  "config_hash": "a3f7…"
}
```

### 3.3 Attributs CF obligatoires par variable

**Règle** : `xarray.open_zarr(path, consolidated=True)` doit produire un `Dataset` dont tous les champs sont auto-décrits. Chaque DataArray porte :

```python
# exemple pour 'head'
head.attrs = {
    "units": "m",
    "standard_name": "water_table_altitude",     # ou "groundwater_head"
    "long_name": "Hydraulic head above NGF69 datum",
    "_FillValue": np.float32(-9999.0),
    "valid_min": np.float32(-500.0),
    "valid_max": np.float32(5000.0),
    "grid_mapping": "crs",
    "mesh": "mesh",
    "location": "face",
    "coordinates": "time layer face_x face_y",
    "cell_methods": "time: point area: mean",
}

# exemple pour 'recharge'
recharge.attrs = {
    "units": "m s-1",
    "standard_name": "water_flux_density",
    "long_name": "Groundwater recharge flux (RCH package)",
    "_FillValue": np.float32(-9999.0),
    "grid_mapping": "crs",
    "mesh": "mesh",
    "location": "face",
}
```

Un registre des standard_name par variable est maintenu dans `hydromodpy/results/schema/cf_registry.py` `[NOUVEAU]` :

```python
CF_REGISTRY: dict[str, dict] = {
    "head": {
        "standard_name": "water_table_altitude",
        "units": "m",
        "long_name": "Hydraulic head",
    },
    "drawdown":      {"standard_name": "water_table_drawdown", "units": "m"},
    "concentration": {"standard_name": "mass_concentration_of_unspecified_chemical_species_in_water",
                      "units": "kg m-3"},
    "recharge":      {"standard_name": "water_flux_density", "units": "m s-1"},
    "drain":         {"standard_name": "water_volume_transport_into_sea_water_from_rivers",
                      "units": "m3 s-1"},
    "watertable_depth": {"standard_name": "depth_of_water_table_below_surface",
                         "units": "m"},
    "seepage_mask":  {"standard_name": "binary_mask",
                      "units": "1", "flag_values": [0, 1],
                      "flag_meanings": "no_seepage seepage"},
}
```

### 3.4 Chunking justifié

Le chunking actuel `(1, n_layers, n_cells)` (chunk = 1 snapshot complète) est **pathologique pour les timeseries**. La stratégie cible est **paramétrable** via `ResultsConfig.chunk_strategy` :

| Stratégie | `chunks=` | Cas optimisé | Cas pénalisé |
|---|---|---|---|
| `map` (ex-actuel) | `(1, L, N)` | Carte à un instant | Timeseries 1 point → lit n_t chunks |
| `timeseries` | `(n_t, L, 1)` | Timeseries 1 point | Carte à t=k → lit n_face chunks |
| **`balanced` (défaut)** | `(chunk_t, L, chunk_c)` calibré à ~16 MB décompressés | Compromis carte + ts | Neither pire que 4× |

**Algorithme de calibration `balanced`** (`hydromodpy/results/storage/codecs.py`) :

```python
TARGET_CHUNK_BYTES = 16 * 1024 * 1024   # 16 MiB décompressés
def balanced_chunks(n_t: int, n_layers: int, n_face: int,
                    dtype_bytes: int = 4) -> tuple[int, int, int]:
    # chunk_t × n_layers × chunk_c × dtype_bytes ≈ 16 MB
    # On veut chunk_t et chunk_c de même ordre (sqrt partition).
    total = n_t * n_layers * n_face * dtype_bytes
    if total < TARGET_CHUNK_BYTES:
        return (n_t, n_layers, n_face)           # un seul chunk
    ratio = n_t / n_face
    budget = TARGET_CHUNK_BYTES / (n_layers * dtype_bytes)  # chunk_t * chunk_c
    chunk_t = int(np.clip(round(np.sqrt(budget * ratio)), 1, n_t))
    chunk_c = int(np.clip(round(np.sqrt(budget / ratio)),  1, n_face))
    return (chunk_t, n_layers, chunk_c)
```

Pour `n_face = 100 000`, `n_layers = 3`, `n_t = 3 650` : résultat `(180, 3, 5000)` soit **21.6 MB** par chunk.
- Carte à t=k : lit `ceil(100 000 / 5000) = 20` chunks ≈ 430 MB → acceptable.
- Timeseries 1 point : lit `ceil(3650 / 180) = 21` chunks ≈ 450 MB → comparable.

→ **Symétrique**, borne haute < 500 MB dans les deux cas, contre 730 MB actuel pour le cas `timeseries`.

**Écriture streaming** : l'extracteur écrit dans un **buffer temporaire** `(chunk_t, n_layers, n_face)` qui est flushé tous les `chunk_t` timesteps. Le solveur ne voit pas cette complexité.

### 3.5 Codecs et compression

```python
# hydromodpy/results/storage/codecs.py
from zarr.codecs import BloscCodec, BloscShuffle, BloscCname

def codec_for(variable: str, dtype: np.dtype) -> list:
    """Codec optimal par variable."""
    if variable == "seepage_mask":
        # uint8 binaire : shuffle + ZSTD max
        return [BloscCodec(cname=BloscCname.zstd, clevel=5,
                           shuffle=BloscShuffle.bitshuffle)]
    if dtype == np.float32:
        # Floats lisses hydro : byte-shuffle gain 20-40%
        return [BloscCodec(cname=BloscCname.zstd, clevel=3,
                           shuffle=BloscShuffle.shuffle)]
    if dtype in (np.int32, np.int64):
        # Entiers (indices) : bitshuffle + ZSTD
        return [BloscCodec(cname=BloscCname.zstd, clevel=3,
                           shuffle=BloscShuffle.bitshuffle)]
    return [BloscCodec(cname=BloscCname.zstd, clevel=3,
                       shuffle=BloscShuffle.shuffle)]
```

Bilan : ZSTD clevel=3 partout, **shuffle activé** (gain gratuit de 20-40 % sur floats), niveau 5 sur les masques binaires (presque "gratuit" car RLE naturel).

### 3.6 Représentation unifiée DIS / DISV / DISU

Voir `doc 03 §3`. Règle invariante : le Zarr ne connaît que la dimension `face`. L'ordonnancement cellulaire est :

| Topologie | Mapping `face_id → domaine MODFLOW` | Attribut `.zattrs.face_ordering` |
|---|---|---|
| DIS régulière | `face_id = row * ncol + col` (C order) | `"row_major_C"` |
| DISV vertex | identité (MODFLOW 6 utilise déjà un index cellulaire linéaire) | `"disv_native"` |
| DISU non-structuré | identité (indexation nœud MODFLOW-NWT) | `"disu_native"` |

Un helper `UGridMesh.face_to_row_col(face_id)` existe uniquement pour `"row_major_C"` et lève `TopologyError` sinon. La lecture d'un champ est identique quelle que soit la topologie :

```python
ds = xr.open_zarr("simulations/<uuid>.zarr/", consolidated=True)
head = ds["head"]  # dims toujours : (time, layer, face)
```

### 3.7 Version Zarr : choix explicite

Décision documentée dans `ResultsConfig.zarr_format: Literal[2, 3] = 3` :

- **Défaut v3** pour nouveaux projets (codecs riches, consolidated metadata natif, futur-proof).
- **Option v2** pour interopérabilité QGIS-MDAL et ParaView-VTK-Zarr (lecture seule). Quand activé, le layout reste identique, seuls les codecs v2-compatibles sont utilisés (pas de `BloscShuffle.bitshuffle`).

Le format utilisé est écrit dans `.zattrs.zarr_format` pour la détection à la lecture.

---

## 4. Séries ponctuelles en Parquet

### 4.1 Justification du choix Parquet (et non DuckDB)

**Double stockage** : les chroniques ponctuelles existent en **deux endroits** :

| Emplacement | Format | Rôle |
|---|---|---|
| `hydromodpy.duckdb.timeseries` | DuckDB table | **Requête SQL transversale** (multi-sims, JOIN avec observations, filtres complexes) |
| `simulations/<uuid>.zarr/timeseries/simulated.parquet` | Parquet plat | **Autonomie du Zarr** (un `.zarr/` copié ailleurs doit rester lisible) |

L'écriture est **atomique entre les deux** : `write_timeseries()` écrit DuckDB puis appose le Parquet quand `finalize()` est appelé. Les deux sont synchronisés par hash.

### 4.2 Schéma Parquet `timeseries/simulated.parquet`

| Colonne | Type Arrow | Description |
|---|---|---|
| `station_id` | `dictionary<string>` | FK vers `stations.geoparquet` |
| `variable` | `dictionary<string>` | `'head'`, `'discharge'`, `'concentration'`, … |
| `datetime` | `timestamp[ns, UTC]` | Index |
| `value` | `float32` | Valeur simulée |
| `unit` | `dictionary<string>` | CF unit |
| `qflag` | `dictionary<string>` | `'simulated'`, `'gap'`, `'spinup'` |
| `layer` | `int16` | Couche (utile pour head multi-couche) |

Trié par `(station_id, variable, datetime)`, Dictionary-encoded pour les colonnes catégorielles. Row-group size : 128 Ki lignes.

Métadonnées Parquet (`.arrow_schema.metadata`) :

```
"hmp_sim_id":      "<uuid>"
"hmp_version":     "0.4.2"
"created_at":      "2026-04-18T14:22:00Z"
"schema_version":  "1"
```

### 4.3 Schéma GeoParquet `timeseries/stations.geoparquet`

| Colonne | Type | Description |
|---|---|---|
| `station_id` | `string` | PK |
| `name` | `string` | label humain |
| `provider` | `dictionary<string>` | `'hubeau'`, `'custom'` |
| `variable` | `list<dictionary<string>>` | variables observées |
| `altitude_m` | `float32` | |
| `cell_id` | `int32` | face associée dans le mesh |
| `geometry` | `geoarrow.point` | Point 2D dans `crs_wkt` |

Lisible directement par `geopandas.read_parquet()`. Conforme GeoParquet 1.1.

---

## 5. API Python

Organisation par fichier (cohérent avec `01_structure_packages.md §6.8`) :

```
hydromodpy/results/
├── __init__.py                    Exports publics
├── catalog/
│   ├── __init__.py                SimulationCatalog façade
│   ├── catalog.py                 Lifecycle + connection (≤ 200 l.)
│   ├── writes.py                  write_*, register_* (≤ 300 l.)
│   ├── queries.py                 query_*, find, best, latest (≤ 200 l.)
│   ├── package.py                 export_simulation, import_simulation (≤ 250 l.)
│   └── migrations.py              SCHEMA_VERSION + MIGRATIONS (≤ 200 l.)
├── schema/
│   ├── __init__.py                SCHEMA_VERSION
│   ├── tables.py                  DDL (§2.2)
│   ├── views.py                   DDL des vues (§2.3)
│   └── cf_registry.py             CF_REGISTRY (§3.3)
├── storage/
│   ├── __init__.py                SimulationZarr
│   ├── zarr_store.py              SimulationZarr (wrap Zarr) (≤ 350 l.)
│   ├── spec.py                    Layout Zarr formel (paths, dtypes, chunks)
│   └── codecs.py                  balanced_chunks, codec_for
├── simulation.py                  Simulation (wrapper sim_id) (≤ 300 l.)
├── simulation_group.py            SimulationGroup (≤ 250 l.)
├── virtual_fields.py              Champs dérivés vectorisés
├── spatial_index.py               STRtree cached
├── provenance.py                  PROV-O : sign_artifact, record_run_environment
├── config.py                      ResultsConfig (Pydantic)
└── io/
    ├── __init__.py                registry auto
    ├── exporter_base.py           Exporter Protocol
    ├── registry.py                register_exporter
    ├── _common.py                 _find_variable, load_mesh (DRY exporters)
    └── exporters/
        ├── netcdf.py              NetCDF CF-1.11 + UGRID-1.0 strict
        ├── geotiff.py             COG (tiled, LZW)
        ├── geopackage.py          GPKG (primaire)
        ├── shapefile.py           legacy
        ├── vtu.py                 FIX _split_cell_data
        ├── csv.py                 + datapackage.json sidecar
        └── waterml.py             WaterML 2.0 pour stations
```

### 5.1 `SimulationCatalog` — interface publique

```python
# hydromodpy/results/catalog/catalog.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Iterable, Literal, Self
from uuid import UUID
import duckdb, pandas as pd, xarray as xr, geopandas as gpd
from filelock import FileLock, Timeout

from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.results.schema import SCHEMA_VERSION
from hydromodpy.results.catalog.migrations import migrate
from hydromodpy.results.storage import SimulationZarr
from hydromodpy.results.simulation import Simulation
from hydromodpy.results.simulation_group import SimulationGroup


class SimulationCatalog:
    """
    Unified simulation catalog (DuckDB + Zarr) for a HydroModPy workspace.

    Usage
    -----
    >>> with SimulationCatalog("~/ws", read_only=False) as catalog:
    ...     sim = catalog.best(project="canut", metric="nse")
    ...     ds = sim.to_xarray(variables=["head"])
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __init__(
        self,
        workspace_path: str | Path,
        *,
        read_only: bool = False,
        lock_timeout: float = 5.0,
        auto_migrate: bool = True,
    ) -> None: ...

    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, *exc) -> None: ...

    # Properties
    @property
    def workspace_path(self) -> Path: ...
    @property
    def connection(self) -> duckdb.DuckDBPyConnection: ...
    @property
    def schema_version(self) -> int: ...
    @property
    def simulations(self) -> pd.DataFrame:
        """DataFrame of v_simulation_summary."""

    # ------------------------------------------------------------------
    # Registration (streaming-safe, idempotent)
    # ------------------------------------------------------------------
    def register_simulation(
        self,
        *,
        project: str,
        solver: str,
        flow_regime: Literal["steady", "transient", "steady_then_transient"],
        config: HydroModPyConfig,
        mesh_topology: Literal["dis", "disv", "disu"],
        mesh_hash: str,
        crs_wkt: str,
        n_cells: int,
        n_layers: int,
        bbox: tuple[float, float, float, float],
        sim_id: UUID | None = None,
        name: str | None = None,
        n_timesteps: int | None = None,
        period_start: pd.Timestamp | None = None,
        period_end: pd.Timestamp | None = None,
        time_unit: str = "day",
        parent_sim_id: UUID | None = None,
        lineage_kind: str | None = None,
        notes: str | None = None,
    ) -> SimulationZarr:
        """Register a new simulation. Returns the Zarr writer."""

    def record_run_environment(
        self, sim_id: UUID, *, user_login: str | None = None, …
    ) -> None: ...

    def finalize(
        self,
        sim_id: UUID,
        *,
        status: Literal["completed", "failed", "aborted"] = "completed",
        pack_zarr: bool = True,
    ) -> None:
        """Mark status=completed, pack Zarr into .zip, flush Parquet, commit."""

    # ------------------------------------------------------------------
    # Writes (streaming-safe, UPSERT via ON CONFLICT DO UPDATE)
    # ------------------------------------------------------------------
    def write_parameters(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_timeseries(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_budgets(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_mass_balance(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_metrics(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_provenance(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_observation_points(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_observations(self, sim_id: UUID, data: pd.DataFrame) -> None: ...
    def write_geographic_feature(
        self, sim_id: UUID, feature_name: str, gdf: gpd.GeoDataFrame,
        *, properties: dict | None = None,
    ) -> None: ...
    def write_geographic_metadata(
        self, sim_id: UUID, key: str, value: Any, *,
        value_type: str = "string", unit: str | None = None,
    ) -> None: ...
    def write_tags(self, sim_id: UUID, tags: Iterable[str]) -> None: ...

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list_simulations(self, **filters: Any) -> pd.DataFrame:
        """Filters: project=, solver=, status=, nse_gt=, created_after=, tag=…"""
    def find(self, **filters: Any) -> SimulationGroup: ...
    def best(self, project: str, *, metric: str = "nse",
             station_id: str = "__outlet__", variable: str = "discharge") -> Simulation: ...
    def latest(self, project: str | None = None) -> Simulation: ...
    def __getitem__(self, sim_id: UUID | str) -> Simulation: ...
    def __contains__(self, sim_id: UUID | str) -> bool: ...
    def __iter__(self) -> Iterable[Simulation]: ...

    def query_timeseries(
        self, sim_id: UUID, *, station_id: str | None = None,
        variable: str | None = None,
    ) -> pd.DataFrame: ...
    def query_budgets(self, sim_id: UUID, *, zone_id=None, component=None) -> pd.DataFrame: ...
    def query_mass_balance(self, sim_id: UUID) -> pd.DataFrame: ...
    def query_metrics(self, sim_id: UUID) -> pd.DataFrame: ...
    def query_parameters(self, sim_id: UUID) -> pd.DataFrame: ...
    def query_provenance(self, sim_id: UUID) -> pd.DataFrame: ...
    def query_run_environment(self, sim_id: UUID) -> pd.DataFrame: ...

    # ------------------------------------------------------------------
    # Zarr access
    # ------------------------------------------------------------------
    def open_zarr(self, sim_id: UUID, *, mode: Literal["r", "r+"] = "r") -> SimulationZarr: ...

    # ------------------------------------------------------------------
    # Pivot / ML export
    # ------------------------------------------------------------------
    def to_dataframe(
        self,
        *,
        sim_ids: Iterable[UUID] | None = None,
        params: Iterable[str] | None = None,
        metrics: Iterable[str] | None = None,
        metadata: Iterable[str] = ("project", "solver", "n_cells"),
    ) -> pd.DataFrame:
        """
        Wide DataFrame (one row = one simulation) joining params and metrics.
        Columns : [sim_id, project, solver, ...metadata, param_K, param_Sy, metric_nse, metric_kge, ...]
        """

    def to_xarray(
        self,
        sim_id: UUID,
        *,
        variables: Iterable[str] | None = None,
        consolidated: bool = True,
    ) -> xr.Dataset:
        """xr.open_zarr equivalent, with UGRID decoded and CRS attached."""

    # ------------------------------------------------------------------
    # Export / Import portable
    # ------------------------------------------------------------------
    def export_simulation(
        self,
        sim_id: UUID,
        output: str | Path,
        *,
        include_fields: Iterable[str] | Literal["all", "none"] = "all",
        include_timeseries: bool = True,
        include_geographic: bool = True,
        include_config: bool = True,
        compression: Literal["zstd", "gzip"] = "zstd",
        compression_level: int = 6,
    ) -> Path:
        """Write an '.hmp' archive containing manifest + catalog rows + Zarr."""

    def import_simulation(
        self,
        package: str | Path,
        *,
        project: str | None = None,
        allow_overwrite: bool = False,
        remap_sim_id: bool = False,
    ) -> UUID: ...

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------
    def sql(self, query: str, params: list | None = None) -> pd.DataFrame: ...
    def migrate(self, *, target: int | None = None) -> int: ...
    def cleanup(
        self,
        sim_ids: Iterable[UUID] | None = None,
        *,
        status: Literal["failed", "aborted"] | None = None,
        older_than: pd.Timedelta | None = None,
        delete_zarr: bool = True,
    ) -> list[UUID]: ...
    def vacuum(self) -> None:
        """DuckDB CHECKPOINT + VACUUM; compact Zarr if packed."""
```

### 5.2 `Simulation` — wrapper haut niveau

```python
# hydromodpy/results/simulation.py
class Simulation:
    """High-level wrapper around a sim_id. All data access is lazy."""

    def __init__(self, catalog: SimulationCatalog, sim_id: UUID): ...

    # Metadata (cached after first access)
    @property
    def id(self) -> UUID: ...
    @property
    def name(self) -> str | None: ...
    @property
    def project(self) -> str: ...
    @property
    def solver(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def config(self) -> HydroModPyConfig: ...
    @property
    def metadata(self) -> dict[str, Any]:
        """All columns of the simulations row + geographic_metadata dict."""

    # Lazy DataFrames (cached)
    @property
    def parameters(self) -> pd.DataFrame: ...
    @property
    def metrics(self) -> pd.DataFrame: ...
    @property
    def mass_balance(self) -> pd.DataFrame: ...
    @property
    def provenance(self) -> pd.DataFrame: ...
    @property
    def tags(self) -> list[str]: ...

    # Zarr access
    @property
    def zarr(self) -> SimulationZarr: ...
    @property
    def mesh(self) -> "UGridMesh": ...

    # Data queries
    def timeseries(
        self, *, station_id: str | None = None, variable: str | None = None,
    ) -> pd.DataFrame: ...
    def budget(self, *, zone_id=None, component=None) -> pd.DataFrame: ...

    def field(
        self, name: str, *,
        time: pd.Timestamp | slice | int | None = None,
        layer: int | slice | None = None,
    ) -> xr.DataArray:
        """Always returns xarray. time can be ISO str, int index, slice, or None (all)."""

    def to_xarray(self, variables: Iterable[str] | None = None) -> xr.Dataset: ...
    def geographic(self, feature_name: str) -> gpd.GeoDataFrame: ...
    def geographic_raster(self, name: str) -> xr.DataArray: ...

    # Exports
    def export(
        self, format: Literal["netcdf", "geotiff", "vtu", "csv", "geopackage", "waterml"],
        output: str | Path, **options: Any,
    ) -> Path: ...

    # Display (delegates to analysis/display)
    def plot(self, figure_name: str, **kwargs: Any) -> "matplotlib.figure.Figure": ...
    def figures(self) -> list[str]:
        """Available figure names for this simulation."""
```

### 5.3 `SimulationGroup` — opérations groupées

```python
# hydromodpy/results/simulation_group.py
class SimulationGroup:
    """Group of simulations produced by catalog.find() or .filter()."""

    def __init__(self, catalog: SimulationCatalog, sim_ids: list[UUID]): ...

    # Sequence protocol
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterable[Simulation]: ...
    def __getitem__(self, index: int | slice) -> Simulation | "SimulationGroup": ...

    # Filtering / sorting
    def filter(self, **criteria: Any) -> "SimulationGroup": ...
    def sort_by(self, metric: str, *, ascending: bool = True) -> "SimulationGroup": ...
    def best(self, metric: str = "nse") -> Simulation: ...
    def worst(self, metric: str = "nse") -> Simulation: ...
    def top(self, n: int, *, metric: str = "nse") -> "SimulationGroup": ...

    # Aggregated DataFrames
    @property
    def parameters(self) -> pd.DataFrame:
        """Wide DataFrame, one row = one sim, columns = param_names."""
    @property
    def metrics(self) -> pd.DataFrame:
        """Wide DataFrame, one row = one sim, columns = metric_names."""

    # ML-ready export (most-used method for data scientists)
    def to_dataframe(
        self, *,
        params: Iterable[str] | None = None,
        metrics: Iterable[str] | None = None,
        metadata: Iterable[str] = ("project", "solver", "n_cells", "status"),
    ) -> pd.DataFrame: ...

    # Stack multi-sim on new dimension (xarray)
    def to_xarray(
        self, variable: str, *, dim: str = "sim",
        align: Literal["exact", "intersect", "outer"] = "intersect",
    ) -> xr.DataArray:
        """
        Stack a variable across all sims. Returns DataArray with extra 'sim' dim.
        Fails if meshes differ and align != 'intersect'. Useful for ensemble plots.
        """

    # Bulk exports
    def to_csv(self, path: str | Path) -> Path: ...
    def to_parquet(self, path: str | Path) -> Path: ...
    def compare_timeseries(
        self, station_id: str, variable: str,
    ) -> pd.DataFrame:
        """Long DataFrame with (sim_id, datetime, value) for one station/variable."""
```

### 5.4 `SimulationZarr` — wrapper Zarr

```python
# hydromodpy/results/storage/zarr_store.py
class SimulationZarr:
    """Owns one simulation's Zarr directory. Responsible for streaming writes."""

    def __init__(self, path: Path, *, mode: Literal["r", "r+", "a"] = "r"): ...

    @classmethod
    def create(
        cls, path: Path, *,
        n_cells: int, n_layers: int, n_timesteps: int | None = None,
        chunk_strategy: Literal["map", "timeseries", "balanced"] = "balanced",
        zarr_format: Literal[2, 3] = 3,
        attrs: dict | None = None,
    ) -> "SimulationZarr": ...

    # Mesh write (UGRID, unified)
    def write_mesh(self, mesh: "UGridMesh") -> None: ...
    @property
    def mesh(self) -> "UGridMesh": ...

    # Time axis write
    def write_time(self, times: np.ndarray | pd.DatetimeIndex,
                   *, calendar: str = "standard") -> None: ...

    # Field streaming
    def write_field(
        self, name: str, data: np.ndarray,
        *, timestep: int | slice | None = None,
        metadata: dict | None = None,   # merged with CF_REGISTRY[name]
        overwrite: bool = False,
    ) -> None: ...
    def read_field(self, name: str) -> xr.DataArray: ...

    # Geographic rasters
    def write_geographic_raster(self, name: str, data: np.ndarray,
                                *, transform, crs, nodata=None,
                                metadata: dict | None = None) -> None: ...
    def read_geographic_raster(self, name: str) -> xr.DataArray: ...

    # GeoParquet vectors
    def write_geographic_vector(self, name: str, gdf: gpd.GeoDataFrame) -> None: ...
    def read_geographic_vector(self, name: str) -> gpd.GeoDataFrame: ...

    # Timeseries Parquet
    def write_timeseries_parquet(self, df: pd.DataFrame, kind: str = "simulated") -> None: ...
    def read_timeseries_parquet(self, kind: str = "simulated") -> pd.DataFrame: ...

    # Full Dataset (xarray)
    def to_xarray(self, variables: Iterable[str] | None = None) -> xr.Dataset: ...

    # Lifecycle
    def consolidate_metadata(self) -> None: ...
    def pack_to_zip(self, *, delete_source: bool = True) -> Path: ...
    def close(self) -> None: ...
    def __enter__(self) -> "SimulationZarr": ...
    def __exit__(self, *exc) -> None: ...
```

### 5.5 Accès d'un chercheur ML — 5 cas concrets

```python
import hydromodpy as hmp

# Ouverture du workspace (readonly pour analyse)
catalog = hmp.open("~/workspaces/brittany", read_only=True)

# === CAS 1 : trouver la meilleure simulation par projet ===
best = catalog.best(project="canut", metric="nse")
print(best.metadata)        # dict des métadonnées
print(best.metrics)         # DataFrame NSE/KGE/RMSE par station

# === CAS 2 : dataset ML (params × metrics) ===
df = catalog.to_dataframe(
    params=["K", "Sy", "drn_cond"],
    metrics=["nse", "kge", "rmse"],
    metadata=["project", "solver", "n_cells", "period_start"],
)
# → DataFrame (n_sims, 3+3+4 colonnes), direct vers scikit-learn

# === CAS 3 : xarray + dask sur une sim ===
ds = catalog.to_xarray(best.id, variables=["head", "drawdown"])
# ds.head dims: (time, layer, face) — entièrement CF/UGRID auto-décrit
ds.head.isel(time=-1, layer=0).plot()  # matplotlib direct

# === CAS 4 : comparaison 200 sims d'une session de calibration ===
group = catalog.find(project="canut", status="completed", tag="calibration-session-42")
# filter + sort
top10 = group.top(10, metric="nse")
# Stack pour plot ensemble
ensemble = top10.to_xarray("head", dim="sim", align="intersect")
ensemble.mean(dim="sim").plot()

# === CAS 5 : SQL brut pour analyse avancée ===
df = catalog.sql("""
    SELECT p.param_name, p.value, m.value AS nse
    FROM parameters p
    JOIN metrics m ON p.sim_id = m.sim_id
        AND m.station_id = '__outlet__'
        AND m.metric_name = 'nse'
    JOIN simulations s ON p.sim_id = s.sim_id
    WHERE s.project = 'canut' AND p.param_name = 'K'
""")
```

---

## 6. Format portable `.hmp`

### 6.1 Contenu de l'archive

Un `.hmp` est une archive **`tar`** compressée **zstd** (extension `.hmp` = magic, pas `.tar.zst`).

```
canut-best-2026-04-18.hmp  (= tar.zst)
│
├── manifest.json                     # obligatoire, premier fichier (streamable)
├── simulation.zarr/                  # Zarr COMPLET (ou absent si --metadata-only)
│   └── ...                           # tous les fichiers Zarr v3
├── catalog_rows/                     # lignes DuckDB exportées table par table
│   ├── simulations.parquet
│   ├── parameters.parquet
│   ├── metrics.parquet
│   ├── timeseries.parquet
│   ├── budgets.parquet
│   ├── mass_balance.parquet
│   ├── observation_points.parquet
│   ├── observations.parquet
│   ├── provenance.parquet
│   ├── runs_environment.parquet
│   ├── geographic_features.parquet
│   ├── geographic_metadata.parquet
│   └── tags.parquet
├── config.toml                       # TOML d'origine (human-readable)
├── README.md                         # auto-généré (résumé + comment importer)
└── LICENSE.txt                       # EPL-2.0
```

**Pourquoi `tar.zst`** :
- un fichier unique → partage mail, S3, etc.
- streamable : `manifest.json` en tête → inspection sans décompression complète.
- zstd clevel 6 : ratio ≈ gzip -9, décompression 3× plus rapide.
- format ouvert, portable.

**Alternative considérée et rejetée** : ZIP. Avantage : accès random. Inconvénient : compression moins efficace, pas de streaming tête-de-fichier pour le manifest.

### 6.2 `manifest.json`

```json
{
  "format": "hmp",
  "format_version": 1,
  "hmp_version": "0.4.2",
  "hmp_git_sha": "74b62878",
  "schema_version": 3,
  "exported_at": "2026-04-18T14:22:00Z",
  "exported_by": {
    "user": "bb",
    "host": "fedora43",
    "hmp_version": "0.4.2"
  },

  "simulation": {
    "sim_id": "0a1f9c3d-8e2b-4a7f-bd92-…",
    "name": "canut-best",
    "project": "canut",
    "solver": "modflow6",
    "flow_regime": "transient",
    "period_start": "2020-01-01T00:00:00Z",
    "period_end":   "2022-12-31T00:00:00Z",
    "n_cells": 103204,
    "n_layers": 3,
    "n_timesteps": 1096
  },

  "artifacts": [
    {"path": "simulation.zarr/",        "kind": "zarr",   "sha256": "a1b2…"},
    {"path": "catalog_rows/",           "kind": "parquet-dir", "n_files": 13},
    {"path": "config.toml",             "kind": "toml",   "sha256": "f3e4…"}
  ],
  "artifact_manifest_sha256": "c5d6…",

  "content_flags": {
    "has_zarr":         true,
    "has_timeseries":   true,
    "has_geographic":   true,
    "has_pathlines":    false,
    "fields_included":  ["head", "drawdown", "recharge", "drain"],
    "metadata_only":    false
  },

  "checksum": {
    "algo": "SHA-256",
    "value": "7a8b9c…"    // calculé sur catégories d'artefacts triées (voir §6.5)
  }
}
```

### 6.3 Versioning

Trois niveaux **indépendants** :

| Niveau | Champ | Varie quand |
|---|---|---|
| `format_version` | format du `.hmp` (structure du manifest, layout de l'archive) | Changement de structure archive/manifest |
| `schema_version` | schéma DuckDB (version des `catalog_rows/*.parquet`) | Nouvelle table, nouvelle colonne |
| `hmp_version` | version du logiciel HydroModPy | Chaque release semver |

Règle d'import : `import_simulation()` accepte `format_version ≤ SUPPORTED_FORMAT` et `schema_version ≤ SCHEMA_VERSION`. Si inférieur, applique les migrations nécessaires **en mémoire** avant insertion.

### 6.4 Export partiel

```python
# Tout (défaut)
catalog.export_simulation(sim_id, "full.hmp")

# Seulement les metadata (pour analyse stats sans télécharger le Zarr)
catalog.export_simulation(sim_id, "meta.hmp", include_fields="none",
                          include_timeseries=False, include_geographic=False)
# → manifest + catalog_rows/*.parquet seulement ; ~10 KB

# Seulement quelques champs (réduction du volume Zarr)
catalog.export_simulation(sim_id, "head_only.hmp",
                          include_fields=["head", "watertable_elevation"])

# Config seul pour reproduire la simulation
catalog.export_simulation(sim_id, "config_only.hmp",
                          include_fields="none", include_timeseries=False,
                          include_geographic=False)
# → manifest + simulations.parquet + config.toml
```

L'implémentation filtre le Zarr à la volée (`zarr.copy_store` avec liste blanche) et n'inclut dans l'archive que les fichiers voulus.

### 6.5 Intégrité

Chaque fichier Zarr / Parquet est hashé SHA-256. Le **digest global du manifest** (`artifact_manifest_sha256`) est le hash du tri lexicographique des hashes individuels. À l'import :

1. `tar -I zstd -tf x.hmp` → extraction manifest en premier.
2. Parse manifest → vérifier `format_version`, `schema_version`.
3. Pour chaque `artifact`, comparer `sha256(extracted) == manifest.artifacts[i].sha256`.
4. Si mismatch → lever `PackageIntegrityError`.

### 6.6 Round-trip testé

`tests/unit/results/test_hmp_roundtrip.py` `[NOUVEAU]` :

```python
def test_roundtrip_full(tmp_path, sample_sim):
    """Export + re-import == original."""
    src = SimulationCatalog(tmp_path / "src")
    sim_id = populate_sample(src)
    src.export_simulation(sim_id, tmp_path / "exp.hmp")

    dst = SimulationCatalog(tmp_path / "dst")
    new_id = dst.import_simulation(tmp_path / "exp.hmp")

    # Diff table by table
    for table in CATALOG_TABLES:
        left  = src.sql(f"SELECT * FROM {table} WHERE sim_id = ? ORDER BY 1",
                        [str(sim_id)])
        right = dst.sql(f"SELECT * FROM {table} WHERE sim_id = ? ORDER BY 1",
                        [str(new_id)])
        assert left.reset_index(drop=True).equals(right.reset_index(drop=True))
```

---

## 7. Migrations de schéma

Voir `§2.5` pour le code. Règles opérationnelles :

1. **Un schéma = une version entière monotone**.
2. Chaque migration est **une fonction `up` + optionnellement `down`**. `up` doit être idempotent (`IF NOT EXISTS` / `IF EXISTS`).
3. **Test obligatoire** : snapshot d'une DB à chaque version N dans `tests/fixtures/catalog_v{N}.duckdb`. Test que `migrate()` depuis v(N) produit une DB strictement équivalente à un fresh v(N+1) — comparaison par `INFORMATION_SCHEMA` + COUNT lignes.
4. **Compatibilité du format `.hmp`** : une version `.hmp` v=k est importable tant que le code sait migrer du `schema_version` k.schema_version vers `SCHEMA_VERSION` actuel. Les migrations sont appliquées **en mémoire** sur les parquet avant insertion.
5. **Pas de downgrade silencieux**. Si une DB a `_schema_version.MAX(version) > SCHEMA_VERSION` du code, `SimulationCatalog.__init__` lève `SchemaTooNewError` avec le numéro exact.

---

## 8. Concurrence, robustesse, performance

### 8.1 Single-writer + filelock

```python
# hydromodpy/results/catalog/catalog.py
from filelock import FileLock, Timeout

class SimulationCatalog:
    def __init__(self, workspace_path, *, read_only=False, lock_timeout=5.0):
        self._ws = Path(workspace_path).expanduser().resolve()
        self._db_path = self._ws / "hydromodpy.duckdb"
        self._lock_path = self._ws / "hydromodpy.duckdb.lock"

        if not read_only:
            self._lock = FileLock(self._lock_path, thread_local=False)
            try:
                self._lock.acquire(timeout=lock_timeout)
            except Timeout:
                raise WorkspaceLockedError(
                    f"Workspace {self._ws} is locked by another process. "
                    f"Delete {self._lock_path} if stale."
                )
        else:
            self._lock = None

        self._conn = duckdb.connect(str(self._db_path), read_only=read_only)
        if not read_only:
            migrate(self._conn)
```

**Multi-reader OK** : chaque process qui ouvre en `read_only=True` ne prend pas le lock. DuckDB supporte N readers + 1 writer.

### 8.2 Écritures atomiques

Tout bloc d'écriture passe par une transaction explicite :

```python
def write_timeseries(self, sim_id, data):
    with self._conn.cursor() as c:
        c.begin()
        try:
            c.executemany("""
                INSERT INTO timeseries (sim_id, station_id, variable, datetime, value, unit, qflag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sim_id, station_id, variable, datetime) DO UPDATE
                    SET value = excluded.value, unit = excluded.unit, qflag = excluded.qflag
            """, data.to_records(index=False).tolist())
            c.commit()
        except Exception:
            c.rollback()
            raise
```

**UPSERT via `ON CONFLICT` : l'idempotence est native**. Un solveur qui rejoue un pas de temps écrase proprement.

### 8.3 Recovery après crash

`SimulationCatalog.__init__` exécute au démarrage :

```sql
UPDATE simulations SET status = 'aborted', ended_at = current_timestamp
WHERE status = 'running'
  AND started_at < current_timestamp - INTERVAL 30 MINUTES;
```

Les simulations "running" abandonnées depuis > 30 min sont marquées `aborted`. L'utilisateur peut `cleanup(status='aborted')` pour purger.

### 8.4 Benchmarks attendus

Cible sur workspace typique (10 GB, 1 000 sims) :

| Opération | Temps cible |
|---|---|
| Ouverture `SimulationCatalog(ws)` | < 100 ms |
| `list_simulations()` (1 000 sims) | < 50 ms |
| `to_dataframe(params=[…], metrics=[…])` (1 000 sims × 5 params × 5 metrics) | < 300 ms |
| `best(project="canut")` | < 20 ms |
| `sim.field("head")` (open Zarr) | < 100 ms (lazy dask) |
| `sim.timeseries(station="P01")` | < 20 ms |
| `export_simulation(full, ~1 GB Zarr)` | ~ 5 s (zstd-6) |
| `import_simulation(1 GB .hmp)` | ~ 8 s |

### 8.5 Observabilité

Une table facultative `query_log` (activée par `ResultsConfig.log_queries=True`) trace les opérations :

```sql
CREATE TABLE IF NOT EXISTS query_log (
    ts          TIMESTAMPTZ DEFAULT current_timestamp,
    user_login  VARCHAR, operation VARCHAR, sim_id UUID, duration_ms DOUBLE, details JSON
);
```

Rotation par purge > 90 jours.

---

## 9. Tableau récapitulatif actuel → cible

### 9.1 Tables DuckDB

| Actuel (`catalog_schema.py`) | Cible (`schema/tables.py`) | Statut | Changements clés |
|---|---|---|---|
| `_schema_version` | `_schema_version` | `[REFACTORE]` | + `description` + `hmp_version` NOT NULL |
| `simulations` | `simulations` | `[REFACTORE]` | PK UUID conservée ; `period_*` → `TIMESTAMPTZ` ; `crs` → `crs_wkt` + `crs_epsg` ; `bbox[4]` → 4 colonnes ; `cell_types[]` SUPPRIMÉ (dans Zarr) ; `tags[]` → table `tags` ; FK self `parent_sim_id` ajoutée ; `started_at`/`ended_at` ajoutés |
| `parameters` | `parameters` | `[CONSERVE]` | PK OK, `DEFAULT '__global__'` sur zone_id |
| `timeseries` | `timeseries` | `[REFACTORE]` | + PK (sim,station,var,datetime) ; `timestamp` → `datetime TIMESTAMPTZ` ; + FK CASCADE |
| `budgets` | `budgets` | `[REFACTORE]` | + PK (sim,timestep,zone,component) ; `component` → ENUM ; + FK CASCADE |
| `mass_balance` | `mass_balance` | `[REFACTORE]` | + PK (sim,timestep) ; + FK CASCADE |
| `metrics` | `metrics` | `[REFACTORE]` | + colonne `variable` dans la PK ; `metric_name` → ENUM ; + FK CASCADE |
| `observation_points` | `observation_points` | `[REFACTORE]` | + PK (sim,station) ; `variable` SUPPRIMÉ (redondant) ; + FK CASCADE |
| `provenance` | `provenance` | `[REFACTORE]` | + PK (sim,variable,source_ref) ; + `source_sha256` (hash fichier) et `payload_sha256` (hash array) ; `period_*` → TIMESTAMPTZ |
| `calibration_sessions` | `calibration_sessions` | `[REFACTORE]` | + FK `best_sim_id` SET NULL ; `status` ENUM |
| `calibration_iterations` | `calibration_iterations` | `[REFACTORE]` | + FK CASCADE session ; + FK `sim_id` SET NULL |
| `geographic_features` | `geographic_features` | `[REFACTORE]` | `geojson TEXT` SUPPRIMÉ → `geoparquet_path` pointe vers GeoParquet dans le Zarr ; `geometry_type` → ENUM |
| `geographic_metadata` | `geographic_metadata` | `[REFACTORE]` | + `value_type` + `unit` |
| — | `runs_environment` | `[NOUVEAU]` | Provenance scientifique (user/host/git/python/solver) |
| — | `stations` | `[NOUVEAU]` | Stations indépendantes (miroir indexable du cache) |
| — | `tags` | `[NOUVEAU]` | Normalisation ex-`simulations.tags[]` |
| — | `observations` | `[NOUVEAU]` | Chroniques observées matérialisées (pour JOIN calage) |
| — | `v_simulation_summary` | `[NOUVEAU]` | Vue dénormalisée |
| — | `v_best_per_project` | `[NOUVEAU]` | Vue classement |
| — | `v_params_wide` | `[NOUVEAU]` | PIVOT auto |
| — | `v_metrics_wide` | `[NOUVEAU]` | PIVOT auto |
| — | `v_simulation_inputs_provenance` | `[NOUVEAU]` | Cross-DB avec cache |

### 9.2 Zarr

| Actuel (`zarr_store.py`) | Cible (`storage/zarr_store.py`) | Statut |
|---|---|---|
| `root/<variable>` (3D `(t,l,c)`) | `root/<variable>` (3D `(t,l,face)`) | `[CONSERVE]` layout |
| chunks `(1, l, c)` | chunks `balanced(t,l,face)` ~16 MB | `[REFACTORE]` |
| BLOSC-ZSTD clevel=3, no shuffle | BLOSC-ZSTD clevel=3 + **shuffle** + bitshuffle pour masques | `[REFACTORE]` |
| `mesh/{vertices, face_node_connectivity, z_interfaces}` | `mesh/` UGRID complet (+ `node_x/y`, `face_x/y`, `mesh` scalar) | `[REFACTORE]` |
| Pas d'attributs CF | Attributs CF-1.11 obligatoires via `CF_REGISTRY` | `[REFACTORE]` |
| Pas de `consolidate_metadata` | `consolidate_metadata()` appelé à `finalize()` | `[NOUVEAU]` |
| Pas de `time` axis | `time` array CF (`units="days since ..."`) | `[NOUVEAU]` |
| `forcing/` groupe | SUPPRIME (remplace par Parquet timeseries + provenance link) | `[SUPPRIME]` |
| Pas de `timeseries/*.parquet` | `timeseries/simulated.parquet` + `stations.geoparquet` | `[NOUVEAU]` |
| Pas de `crs` scalar | `crs` scalar CF avec `grid_mapping_name` + `crs_wkt` | `[NOUVEAU]` |
| `geographic/<name>` (raster) | idem + `geographic/<name>.parquet` pour vecteurs | `[REFACTORE]` |
| ZipStore pour finalize | idem + `consolidated=True` obligatoire | `[CONSERVE]` |

### 9.3 API publique `results/`

| Actuel | Cible | Statut |
|---|---|---|
| `SimulationCatalog` (catalog.py 920 l.) | `SimulationCatalog` (catalog/{catalog,writes,queries,package,migrations}.py) | `[REFACTORE]` éclaté |
| `write_budget` + `write_budgets` (doublon) | `write_budgets` seul (batch) | `[REFACTORE]` |
| `write_mass_balance` + `write_mass_balances` | `write_mass_balance` seul (batch) | `[REFACTORE]` |
| `write_field` (sur root) | `write_field` (sur root + métadonnées CF auto) | `[REFACTORE]` |
| `record_provenance` alias | supprimé | `[SUPPRIME]` |
| `project_path` alias | supprimé | `[SUPPRIME]` |
| `open_zarr_group(mode=...)` | `open_zarr(mode=...)` | `[REFACTORE]` |
| `Simulation.rerun()` (NotImplementedError) | supprimé | `[SUPPRIME]` |
| `Simulation.plot_all` | `Simulation.figures()` + `plot(name)` | `[REFACTORE]` |
| `SimulationGroup.count` | `len(group)` | `[REFACTORE]` |
| `SimulationGroup.to_dataframe()` | `to_dataframe(params=, metrics=, metadata=)` | `[REFACTORE]` enrichi |
| — | `SimulationGroup.to_xarray(variable, dim="sim")` | `[NOUVEAU]` |
| — | `Simulation.to_xarray()` | `[NOUVEAU]` |
| — | `catalog.to_dataframe(params=, metrics=)` | `[NOUVEAU]` |
| — | `catalog.record_run_environment()` | `[NOUVEAU]` |
| — | `catalog.finalize()` | `[NOUVEAU]` |
| `catalog.export_simulation()` | `export_simulation(include_fields=, compression=)` | `[REFACTORE]` + bug if/else fixé + .hmp tar.zst |
| `catalog.import_simulation()` | `import_simulation(remap_sim_id=)` + integrity check | `[REFACTORE]` |
| `resample.py` | supprimé | `[SUPPRIME]` |
| `display.py` | déplacé vers `analysis/display/posthoc.py` | `[RENOMME]` |

### 9.4 Exporters `results/io/exporters/`

| Actuel | Cible | Statut |
|---|---|---|
| `netcdf.py` (UGRID partiel, pas CF) | `netcdf.py` (CF-1.11 + UGRID-1.0 strict) | `[REFACTORE]` |
| `geotiff.py` (non COG) | `geotiff.py` (COG : tiled + LZW) | `[REFACTORE]` |
| `shapefile.py` (primaire) | `shapefile.py` (legacy seulement) | `[REFACTORE]` |
| — | `geopackage.py` (primaire) | `[NOUVEAU]` |
| `vtu.py` (bug `_split_cell_data`) | `vtu.py` corrigé avec masques | `[REFACTORE]` |
| `csv.py` (pas de header metadata) | `csv.py` + `datapackage.json` sidecar | `[REFACTORE]` |
| — | `waterml.py` (WaterML 2.0 stations) | `[NOUVEAU]` |
| `_find_variable` dupliqué ×4 | `io/_common.py::find_variable` | `[REFACTORE]` DRY |
| — | `io/registry.py::Exporter Protocol + register_exporter` | `[NOUVEAU]` |

---

## 10. Exemples d'usage notebook

### 10.1 Session typique d'un hydrogéologue

```python
import hydromodpy as hmp
import matplotlib.pyplot as plt

catalog = hmp.open("~/workspaces/brittany", read_only=True)

# Vue d'ensemble
print(catalog.simulations.head())     # 1 ligne par sim, colonnes clés
# → DataFrame(sim_id, name, project, solver, status, nse_outlet, kge_outlet,
#             n_cells, n_layers, duration_s, created_at, user_login, git_sha)

# Meilleure sim du projet
best = catalog.best(project="canut", metric="nse")
print(best.metadata["nse_outlet"])

# Tracer la chronique d'une station
ts = best.timeseries(station_id="P01", variable="head")
ax = ts.plot(x="datetime", y="value", title=f"Head @ P01 — sim {best.name}")

# Carte de la hauteur piézométrique au dernier instant
head = best.field("head", time=-1, layer=0)     # DataArray (face,)
# Rendu UGRID via plotly ou matplotlib polygons
best.plot("watertable_map", save="~/figures/canut_best_wtmap.png")
```

### 10.2 Session typique d'un data scientist ML

```python
import hydromodpy as hmp
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

catalog = hmp.open("~/workspaces/brittany", read_only=True)

# Dataset (features, target)
df = catalog.to_dataframe(
    params=["K", "Sy", "drn_cond", "rch_mult"],
    metrics=["nse", "kge"],
    metadata=["project", "n_cells", "solver"],
)
df = df[df.project == "canut"].dropna(subset=["nse"])

# Feature importance
X = df[["K", "Sy", "drn_cond", "rch_mult"]].values
y = df["nse"].values
model = RandomForestRegressor(n_estimators=200).fit(X, y)
for col, imp in zip(["K", "Sy", "drn_cond", "rch_mult"], model.feature_importances_):
    print(f"{col}: {imp:.3f}")

# Dataset ensemble head — 10 meilleures sims, coupé sur la dernière année
group = catalog.find(project="canut").top(10, metric="nse")
ensemble = group.to_xarray("head", dim="sim", align="intersect").sel(
    time=slice("2022-01-01", "2022-12-31")
)
mean_head = ensemble.mean(dim="sim")
std_head  = ensemble.std(dim="sim")
```

### 10.3 Session typique d'un chercheur : reproduire une sim depuis un `.hmp`

```python
import hydromodpy as hmp
from pathlib import Path

# Inspecter un .hmp reçu par mail sans l'importer
info = hmp.inspect_package("/tmp/canut-best.hmp")
print(info["simulation"]["sim_id"],
      info["schema_version"], info["hmp_version"])
# → affiche sim_id, versions, fields_included sans extraire tout le Zarr

# Import dans un workspace local
catalog = hmp.open("~/workspaces/local")
new_id = catalog.import_simulation("/tmp/canut-best.hmp")
sim = catalog[new_id]

# Rejouer : générer un nouveau TOML à partir de la config importée
toml_str = sim.config.to_toml()
Path("rerun.toml").write_text(toml_str)
# Puis ligne de commande : hmp run rerun.toml
```

### 10.4 Session typique depuis QGIS (accès direct)

```
# Sans installer hydromodpy, avec QGIS 3.32+ :

1. "Add Vector Layer" → simulations/<uuid>.zarr/geographic/watershed.parquet
   → GeoParquet lu nativement.

2. "Add Raster Layer" → simulations/<uuid>.zarr/geographic/dem
   → lecture via plugin GDAL/Zarr (ou export COG : hmp export <id> --format geotiff).

3. "Add Mesh Layer" → simulations/<uuid>.zarr.nc (export NetCDF CF-UGRID)
   → lu par MDAL, animation time slider native.
```

---

## 11. Conclusion

Le design cible repose sur **trois piliers** :

1. **DuckDB** pour les métadonnées relationnelles, indexées, transactionnelles, interrogeables en SQL — avec des PK/FK réelles, des types `TIMESTAMPTZ` partout, et un framework de migrations effectif.
2. **Zarr v3 CF-UGRID** pour les champs spatio-temporels, auto-décrits, ouvrables par `xarray.open_zarr()` sans l'API HydroModPy, avec un chunking **balanced** qui répond aussi bien aux accès carte qu'aux timeseries.
3. **Parquet / GeoParquet** dans le Zarr pour les chroniques et vecteurs, qui rendent le Zarr **autonome** et directement lisible par DuckDB, pandas, geopandas, QGIS.

Le format portable `.hmp` (`tar.zst`) rend une simulation **auto-contenue et versionnée** (format_version + schema_version indépendants), avec round-trip export↔import vérifié par test.

L'API Python reste **minimale au niveau public** (`hmp.open()`, `catalog.best()`, `sim.field()`, `group.to_dataframe()`) tout en exposant le **SQL brut** (`catalog.sql()`) pour les usages avancés.

Les trois personae (hydrogéologue QGIS, chercheur Jupyter, data scientist ML) ont **chacun un chemin d'accès direct et non-ambigu** aux données, sans à avoir à écrire du code custom de parsing.

**Feuille de route de mise en œuvre** (voir aussi `03_data_contracts.md §7`) :

| Sprint | Livrable |
|---|---|
| S1 | Refactor DuckDB : PK/FK complètes, types TIMESTAMPTZ, ENUMs, migrations v1 testées |
| S2 | `runs_environment`, `tags`, `stations`, `observations` + vues |
| S3 | Zarr CF-UGRID : `CF_REGISTRY`, `balanced_chunks`, consolidated metadata, `crs` scalaire |
| S4 | Éclatement `catalog.py` (920 l.) en 5 modules ; suppression dead code |
| S5 | Parquet timeseries dans le Zarr ; `to_dataframe(params, metrics)` ; `to_xarray()` |
| S6 | Format `.hmp` (tar.zst + manifest versionné + round-trip) |
| S7 | Exporters DRY (`_common.py`) + GeoPackage + WaterML + COG GeoTIFF + VTU fixé |
| S8 | Tests `tests/unit/results/` complets (schema, migrations, exporters, roundtrip) |

Ce design tranche délibérément plusieurs ambiguïtés de l'actuel :
- **Le projet n'est pas un dossier**, c'est un label. Tout s'écrit dans `workspace/hydromodpy.duckdb`.
- **Le mesh est face-indexé universellement** (UGRID) — DIS/DISV/DISU disparaissent du post-traitement.
- **Un rerun = un nouvel UUID** (pas de versioning "git-like" interne). La traçabilité passe par `parent_sim_id` + `lineage_kind`.
- **Single-writer** assumé, documenté, lockfile explicite. Pas de sur-ingénierie distribuée pour un outil desktop.

Fin du document.
