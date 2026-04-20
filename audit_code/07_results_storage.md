# Audit — Stockage des résultats (`hydromodpy/results/`)

**Auditeur** : expert stockage de données scientifiques (DuckDB, Zarr, HDF5, NetCDF-CF, UGRID, Parquet, PROV-O)
**Branche** : `dev-database` (HEAD `74b62878`, post-merge `dev-refact`)
**Scope** :

- `hydromodpy/results/` (12 fichiers Python, 3 193 lignes) :
  - `catalog.py` (920 l.), `catalog_schema.py` (280 l.), `zarr_store.py` (323 l.)
  - `config.py` (153 l.), `simulation.py` (330 l.), `simulation_group.py` (178 l.)
  - `display.py` (142 l.), `provenance.py` (59 l.), `spatial_index.py` (78 l.)
  - `virtual_fields.py` (97 l.), `resample.py` (31 l.), `__init__.py` (6 l.)
- `hydromodpy/results/exporters/` :
  - `netcdf.py` (155 l.), `geotiff.py` (137 l.), `vtu.py` (127 l.)
  - `shapefile.py` (103 l.), `csv.py` (74 l.), `__init__.py` (0 l.)

**Dépendances** : `duckdb` (non pinné), `zarr>=3.0`, `numpy`, `pandas`,
`xarray` (NetCDF), `rasterio` (GeoTIFF), `meshio` (VTU), `geopandas` + `shapely`
(Shapefile, features, spatial_index).

**Contexte merge** : le merge `dev-refact → dev-database` n'a pas touché ce
package (aucun fichier `results/*.py` dans les listes modifiées/ajoutées). Le
schéma DuckDB + Zarr a été introduit en amont sur `dev-database`. Le lecteur
doit cependant savoir que les extracteurs qui écrivent dans ce catalogue
(`simulation/results/extractors/`) ont été fortement modifiés lors du merge.

---

## Synthèse exécutive

| Aspect | Verdict | Commentaire 1-ligne |
|---|---|---|
| Choix DuckDB pour métadonnées | **acceptable** | OLAP adapté, mono-writer, pas adapté à du concurrent-write |
| Choix Zarr v3 pour champs spatiaux | **conforme** | Bon choix cloud-native ; chunking peu optimisé pour timeseries |
| Schéma DuckDB (normalisation 3NF) | **à améliorer** | Partiellement normalisé ; 3 tables sans PK ; types datetime faux |
| Clés étrangères (FK) | **problématique** | Aucune FK déclarée ; cohérence référentielle purement applicative |
| Migrations de schéma | **problématique** | Framework présent mais vide ; pas de plan de versionning |
| Type `period_start`/`period_end` en VARCHAR | **problématique** | Devrait être `TIMESTAMP` / `DATE` ; impossible de filtrer temporellement côté SQL |
| Chunking Zarr `(1, n_layers, n_cells)` | **à améliorer** | Optimisé pour carte à un instant, pathologique pour timeseries à un point |
| Compression BLOSC-ZSTD clevel=3 | **conforme** | Bon compromis CPU/ratio pour champs hydro ; non tuné par variable |
| Conventions CF-1.8 dans le NetCDF | **à améliorer** | UGRID-1.0 partiel, `standard_name`/`units`/CRS absents |
| Convention UGRID | **acceptable** | `cf_role`, `face_node_connectivity`, `_FillValue=-1` OK |
| VTU (ParaView) | **problématique** | `_split_cell_data` bug : suppose un tri tri-puis-quad non garanti |
| GeoTIFF | **acceptable** | CRS codé en dur à EPSG:2154 (fallback) ; pas de band description |
| Shapefile | **problématique** | Truncature des noms de colonnes DBF > 10 chars non gérée ; pas de `.prj` garanti |
| CSV | **à améliorer** | Pas de header de métadonnées ; pas de unités dans les colonnes |
| Provenance SHA-256 | **à améliorer** | Checksum sur `tobytes()` dépend du dtype et du layout ; pas PROV-O |
| Interopérabilité xarray/QGIS/ParaView | **à améliorer** | Exports OK ; accès direct au Zarr cassé (mesh non-standard) |
| Concurrence / locking | **problématique** | DuckDB mono-writer ; aucune protection dans `catalog.py` |
| Format `.hmp` (package) | **problématique** | Non documenté, non versionné, bug dans `import_simulation` |
| Code dupliqué (`_find_variable`, `_split_cell_data`) | **à améliorer** | 4 copies identiques ; factorisation évidente |
| Dead code (`rerun`, `resample`) | **problématique** | APIs exposées qui lèvent `NotImplementedError` |
| Display « résultats » (`display.py`) | **à améliorer** | Doublonne `analysis/display/` ; stubs inoffensifs |

**Verdict global** : fondations correctes (choix techniques judicieux,
séparation metadata/data propre), mais **implémentation inachevée sur plusieurs
fronts critiques** : pas de FK, pas de migrations fonctionnelles, types SQL
faux, pas de gestion de concurrence, format d'échange non documenté. Le code
ressemble à une **v1 POC promue en prod** : beaucoup de duck-typing, des
heuristiques de lookup (subgroup walk), des exporters dupliqués, des stubs
(`rerun`, `resample`) et un bug de logique dans `import_simulation`.

---

## 1. Choix architectural : DuckDB + Zarr

### 1.1 Comparaison avec les alternatives

| Option | Ce que HydroModPy fait | Alternative A : SQLite + HDF5 | Alternative B : Parquet + Zarr |
|---|---|---|---|
| Metadata | DuckDB (OLAP columnar, vectorisé) | SQLite (OLTP row-based) | Parquet (immutable files) |
| Spatial fields | Zarr v3 (chunked, cloud-native) | HDF5 (hiérarchique, mature) | Zarr v3 |
| Single-writer | Oui | Oui | Oui |
| Multi-reader concurrent | Oui (DuckDB 0.10+) | Oui (WAL) | Oui |
| Cloud (S3/GCS) | Natif Zarr ; DuckDB via `httpfs` | HDF5 mal adapté (pas de range-read partiel sans kerchunk) | Natif (Parquet+Zarr sont les standards Anaconda/Pangeo) |
| Maturité scientifique | DuckDB jeune (2019), Zarr v3 très jeune (2024) | HDF5/NetCDF4 standard depuis 20 ans en sciences | Parquet standard dans Data Science |
| Outillage | `duckdb-cli`, pandas, polars, dbt | `h5py`, `h5repack`, HDFView | `pyarrow`, `duckdb`, Athena, BigQuery |

**Verdict** : **acceptable**. DuckDB + Zarr est un choix **moderne et cohérent
pour un outil de 2026**. Le couplage DuckDB (SQL riche, JOINs, GROUP BY vite) +
Zarr (N-D arrays chunkés) est plus pertinent qu'HDF5 seul qui mélange tout
dans un même fichier et scale mal en cloud. C'est aussi le choix que fait
[Earthmover/Arraylake](https://earthmover.io) et le pattern **Pangeo** moderne.

**Mais** :

- **DuckDB 0.10+ seulement** supporte le concurrent read via attach ; `duckdb`
  non pinné dans `pyproject.toml:72` → risque de backward-incompat si l'utilisateur
  installe une vieille version.
- **Zarr v3** est **très jeune** (spec stabilisée Q3 2024). L'API `zarr.codecs.BloscCodec`
  (`zarr_store.py:14`) est une API v3, incompatible avec la v2. Les utilisateurs
  n'ont pas encore d'outillage mature : QGIS, MDAL, Panoply ne lisent Zarr v3 qu'en
  chantier. **C'est un pari**. Solution alternative raisonnable : **rester en Zarr v2
  jusqu'à 2027** pour bénéficier d'un écosystème compatible (xarray 2024.x lit les deux,
  QGIS ne lit que v2).
- **Pas de `kerchunk`/`virtualizarr`** : impossible de présenter une vue unifiée
  multi-sim (ex. « tous les head NWT sur le bassin X ») sans matérialiser. Un
  catalogue Intake ou STAC serait un ajout naturel.

### 1.2 Risques

| Risque | Probabilité | Impact | Mitigation actuelle |
|---|---|---|---|
| Corruption DuckDB sur crash mid-write | **moyen** | **élevé** | Aucune (pas de checkpoint périodique, pas de backup) |
| Corruption Zarr sur crash | faible | élevé | Zarr écrit chunk-par-chunk (atomique au chunk) ; OK |
| Race condition 2 processes `register_simulation` | **élevé** | moyen | **Aucune** (voir §7) |
| Schéma évolue, DB existantes cassent | **élevé** | élevé | Framework `MIGRATIONS` présent mais **vide** |
| Zarr v3 pas lu par consommateur tiers | moyen | moyen | Fournir exports NetCDF ; mais le `.zarr.zip` reste opaque |
| ZipStore read-only : impossible de rejouer/étendre une sim finalisée | **élevé** | faible | Pas de documentation |

**Recommandation** :

1. **Pinner** `duckdb>=0.10.0,<2.0` dans `pyproject.toml`.
2. **Décider explicitement** si on cible Zarr v2 (portabilité) ou v3 (futur) —
   documenter ce choix dans le `README.md` du package.
3. Implémenter un **`BEGIN EXCLUSIVE` / `DETACH`** autour des writes ou migrer
   vers le mode « append-only parquet » + DuckDB « view » si on veut vraiment
   supporter N writers.

---

## 2. Schéma DuckDB — analyse table par table

Diagramme synthétique des 12 tables (+ `_schema_version`) :

```
                           ┌──────────────────────────┐
                           │  _schema_version         │
                           │  version, applied_at     │
                           └──────────────────────────┘

         ┌──────────────────────────────────────────────────┐
         │  simulations (PK: sim_id UUID)                   │◄──── (toutes les tables
         │  project, solver, flow_regime, status,           │      per-sim référencent
         │  n_cells, n_layers, n_timesteps, cell_types[],   │      sim_id → SANS FK)
         │  bbox[4], crs, period_start/end (VARCHAR ☠),     │
         │  config_toml JSON, config_hash, zarr_path,       │
         │  parent_sim_id (self-ref, pas de FK),            │
         │  mesh_hash, mesh_type, duration_s, tags[], notes │
         └──────────────────────────────────────────────────┘
              ▲                                          ▲
              │                                          │
      ┌───────┴──────┐      ┌──────────────┐     ┌──────┴──────────┐
      │ parameters   │      │ timeseries   │     │ budgets         │
      │ PK(sim,param,│      │ NO PK ☠       │     │ NO PK ☠          │
      │    zone)     │      │ ix_ts_lookup  │     │                 │
      │              │      │ (sim,station, │     │ sim, timestep,  │
      │ param_name,  │      │  var, ts)     │     │ zone_id VARCHAR │
      │ zone_id,     │      │ sim, station, │     │ component,      │
      │ value, unit, │      │ var, timestamp│     │ flux_in/_out,   │
      │ param'zation │      │ value, unit   │     │ unit            │
      └──────────────┘      └──────────────┘     └─────────────────┘

      ┌──────────────┐      ┌──────────────┐     ┌─────────────────┐
      │ mass_balance │      │ metrics      │     │ observation_pts │
      │ NO PK ☠       │      │ PK(sim,sta,  │     │ NO PK ☠          │
      │              │      │    metric)   │     │                 │
      │ sim, timestep│      │              │     │ sim, station,   │
      │ total_in/out │      │ sim, station,│     │ x, y, cell_id,  │
      │ storage_in/  │      │ metric_name, │     │ layer, variable │
      │ out, pct_err │      │ value        │     │                 │
      └──────────────┘      └──────────────┘     └─────────────────┘

      ┌──────────────┐      ┌────────────────────┐  ┌──────────────┐
      │ provenance   │      │calibration_sessions│  │geo_features  │
      │ NO PK ☠       │      │ PK: session_id     │  │ PK(sim,name) │
      │ sim, var,    │      │ best_sim_id (ref,  │  │              │
      │ source_type/ │      │    PAS DE FK)      │  │ sim, name,   │
      │ ref,checksum,│      │ method, n_iter,    │  │ geojson TEXT │
      │ period_*     │      │ best_obj, config,  │  │ geom_type,   │
      │ VARCHAR ☠,    │      │ duration_s         │  │ crs, props   │
      │ stats JSON   │      └────────────────────┘  └──────────────┘
      └──────────────┘      ┌─────────────────────┐ ┌──────────────┐
                            │calibration_iter.    │ │geo_metadata  │
                            │ PK(session,iter)    │ │ PK(sim,key)  │
                            │ parameters JSON,    │ │ sim, key,    │
                            │ objective_value,    │ │ value VARCHAR│
                            │ metrics JSON        │ │              │
                            └─────────────────────┘ └──────────────┘
```

### 2.1 Normalisation (3NF)

| Table | Forme normale atteinte | Problèmes |
|---|---|---|
| `simulations` | **1NF** seulement | `cell_types VARCHAR[]`, `tags VARCHAR[]`, `bbox DOUBLE[4]`, `config_toml JSON` — agrégats dénormalisés. **Acceptable en OLAP**, mais rend les requêtes sur tags/cells_types lentes. |
| `parameters` | **3NF correcte** | PK composite propre, pas de redondance |
| `timeseries` | **2NF seulement** | **Pas de PK** → rien n'empêche les doublons (sim, station, var, timestamp). Bug en attente. |
| `budgets` | **2NF seulement** | Pas de PK. Rien n'empêche de réécrire 2× le budget pour (sim, timestep, zone, component). |
| `mass_balance` | **2NF seulement** | Pas de PK. Pas d'UNIQUE(sim, timestep). |
| `metrics` | **3NF** | PK correcte. |
| `observation_points` | **2NF seulement** | Pas de PK, doublons possibles |
| `provenance` | **2NF seulement** | Pas de PK. Si on réimporte le même fichier 10 fois, 10 lignes identiques. |
| `calibration_sessions` | **3NF** | OK |
| `calibration_iterations` | **3NF** | OK |
| `geographic_features` | **3NF** | PK(sim, name) correcte |
| `geographic_metadata` | **3NF** | PK(sim, key) correcte |

**Verdict** : **à améliorer**. Cinq tables sans PK (`timeseries`, `budgets`,
`mass_balance`, `observation_points`, `provenance`) autorisent des doublons.
Le code de `catalog.py:write_timeseries` (`INSERT` pur) ne déduplique pas.
Si un solveur est relancé (cas courant en dev), on obtient des doublons
silencieux qui faussent les agrégations.

**Recommandation** :

```sql
ALTER TABLE timeseries ADD PRIMARY KEY (sim_id, station_id, variable, timestamp);
ALTER TABLE budgets ADD PRIMARY KEY (sim_id, timestep, zone_id, component);
ALTER TABLE mass_balance ADD PRIMARY KEY (sim_id, timestep);
ALTER TABLE observation_points ADD PRIMARY KEY (sim_id, station_id, variable);
ALTER TABLE provenance ADD PRIMARY KEY (sim_id, variable, source_ref);
```

### 2.2 Clés étrangères (FK)

**Aucune FK déclarée dans le schéma**. Toutes les références (`sim_id`,
`session_id`, `best_sim_id`, `parent_sim_id`) sont des UUID bruts.

| Référence | Devrait être | Actuellement |
|---|---|---|
| `parameters.sim_id → simulations.sim_id` | `FK ON DELETE CASCADE` | Gérée **applicatvement** par `delete()` en boucle sur `PER_SIM_TABLE_NAMES` |
| `timeseries.sim_id → simulations.sim_id` | Idem | Idem |
| `calibration_sessions.best_sim_id → simulations.sim_id` | `FK ON DELETE SET NULL` | Rien |
| `simulations.parent_sim_id → simulations.sim_id` | `FK ON DELETE SET NULL` | Rien |

**Verdict** : **problématique**. DuckDB (depuis 0.9) supporte les FK. L'absence
délibérée est non justifiée. Le nettoyage applicatif dans `catalog.py:898-901`
est correct mais fragile : une interruption entre `DELETE FROM simulations` et
le premier `DELETE FROM parameters` laisse des orphelins (le code commence par
les enfants puis la table parent, c'est heureusement robuste — mais une seule
exception entre deux DELETE enfant et la table est corrompue).

**Recommandation** : ajouter `FOREIGN KEY (sim_id) REFERENCES simulations(sim_id) ON DELETE CASCADE`
sur les 9 tables per-sim.

### 2.3 Types SQL — analyse

| Colonne | Type actuel | Devrait être | Verdict |
|---|---|---|---|
| `simulations.sim_id` | `UUID PRIMARY KEY` | OK | **conforme** |
| `simulations.created_at` | `TIMESTAMP DEFAULT now()` | `TIMESTAMPTZ` (avec TZ) | **à améliorer** — DuckDB distingue `TIMESTAMP` (naïf) et `TIMESTAMPTZ` ; les data managers stockent en UTC mais le type ne le reflète pas |
| `simulations.period_start` | `VARCHAR` | `DATE` ou `TIMESTAMP` | **problématique** — impossible de filtrer `WHERE period_start > '2020-01-01'` sans cast ; casse les index |
| `simulations.period_end` | `VARCHAR` | idem | idem |
| `simulations.config_toml` | `JSON` | OK | **conforme** (mais voir 2.4 : redondance avec `config_hash`) |
| `simulations.bbox` | `DOUBLE[4]` | `STRUCT(minx,miny,maxx,maxy)` ou table dédiée | **acceptable** — DuckDB supporte les arrays mais on perd la sémantique ; `STRUCT` serait plus clair |
| `simulations.cell_types` | `VARCHAR[]` | Normaliser ou `ENUM[]` | **à améliorer** — DuckDB a un `CREATE TYPE cell_type AS ENUM(...)` |
| `simulations.crs` | `VARCHAR` | `VARCHAR` (style EPSG:2154) | **acceptable** |
| `timeseries.timestamp` | `TIMESTAMP` | `TIMESTAMPTZ` | **à améliorer** — voir `created_at` |
| `timeseries.value` | `DOUBLE` | OK | **conforme** |
| `provenance.period_start`/`end` | `VARCHAR` | `TIMESTAMP` | **problématique** |
| `provenance.stats` | `JSON` | OK | **conforme** |
| `budgets.unit` | `VARCHAR DEFAULT 'm3/d'` | OK | **conforme** |
| `geographic_features.geojson` | `TEXT` | `VARCHAR` ou `BLOB` (GeoJSON peut être gros) | **acceptable** (DuckDB `TEXT == VARCHAR`) ; **mais** DuckDB 0.10+ a un **plugin spatial** avec `GEOMETRY` natif — à privilégier si la dépendance est ajoutée |

**Note technique** : en DuckDB, `VARCHAR` et `TEXT` sont **strictement
identiques** (alias). `FLOAT` vs `DOUBLE` : le code utilise `DOUBLE` partout
(bon choix pour des heads et fluxes hydrologiques).

**Verdict** : **à améliorer**. Les `VARCHAR` sur `period_start`/`period_end`
sont le problème le plus grave : impossible d'indexer temporellement, casts
explicites requis. L'absence de timezone est un nid-à-bugs scientifique (des
utilisateurs français vs américains se retrouveront avec des décalages de 6 h
sans warning).

### 2.4 Colonnes redondantes / mauvais emplacement

| Observation | Verdict |
|---|---|
| `simulations.n_cells` / `n_layers` dupliqué dans `mesh.attrs` du Zarr | **dupliqué** — deux sources de vérité. Recommandation : ne garder que dans Zarr, faire lire à la volée. |
| `simulations.config_toml` + `config_hash` | **dupliqué** — le hash peut être recalculé. Acceptable comme index. |
| `simulations.mesh_hash` + `mesh_type` | **acceptable** — utile pour groupby |
| `simulations.solver_category` | **dupliqué** — dérivé de `solver` via dict `SOLVER_CATEGORIES` dans `catalog_schema.py:13-17`. Pourrait être une **vue SQL** plutôt qu'une colonne (mais OK comme dénormalisation de perf). |
| `simulations.bbox` | **dupliqué** avec Zarr `mesh/vertices` (min/max calculable) |
| `observation_points.variable` | **suspect** — pourquoi une obs point serait liée à une `variable` unique ? Devrait être dans `metrics` ou n'avoir aucune mention de variable. |

### 2.5 Migrations de schéma

`catalog_schema.py:238-240` :

```python
MIGRATIONS: dict[int, list[str]] = {
    # 1: [],  # initial schema, no migration needed
}
```

**Verdict** : **problématique**. Le framework est conceptuellement correct
(`LATEST_VERSION`, `_schema_version` table, stamp après migration) mais :

1. Le dict est **vide**. Toute évolution du schéma (ajouter une colonne,
   renommer) cassera les bases existantes **silencieusement** — `CREATE TABLE
   IF NOT EXISTS` ne met pas à jour les tables existantes.
2. **Ordre d'application bogué** : `ensure_schema()` applique les DDL puis
   les migrations. Si la v2 ajoute une colonne, la DDL `CREATE TABLE` v2 ne
   s'appliquera pas (table existe) **et** la migration ne sera pas appliquée
   non plus si on a déjà stampé en v1.
3. Pas de **downgrade** / rollback.
4. Pas de tests sur la migration (`tests/unit/results/` absent).

**Recommandation** : s'inspirer d'**Alembic** (stdlib pour Python), qui gère
les migrations idempotentes avec upgrade/downgrade. Ou plus léger, `yoyo`.
Écrire au moins un test de non-régression qui charge une base snapshotée d'une
version antérieure et vérifie la migration automatique.

---

## 3. Layout Zarr

Diagramme ASCII :

```
simulations/<uuid>.zarr/ (ou <uuid>.zarr.zip après finalize)
├── .zgroup                     # Zarr v3 root
├── .zattrs                     # n_cells, n_layers, cell_types
├── mesh/                       # UGRID topology (in situ)
│   ├── vertices           (n_nodes, 2 or 3)       float64
│   ├── face_node_connectivity (n_cells, max_vpf)  int32     ← -1 padding
│   ├── z_interfaces       (n_layers+1,)           float64
│   ├── layer_indices      (n_cells_3D,)           int32     optional
│   ├── source_cell_indices(n_cells_3D,)           int32     optional
│   ├── .zattrs start_index, n_nodes, n_cells, n_layers
│   └── (surface_top)      ← référencé par virtual_fields mais PAS écrit
│                              par zarr_store (contradiction)
├── <variable> e.g. head/      # PRIMARY state fields (root level)
│   shape  = (n_timesteps, n_layers, n_cells)   # 3D
│        ou (n_timesteps, n_cells)              # 2D
│   chunks = (1,              n_layers, n_cells)
│   dtype  = float64 (usually)
│   codecs = BLOSC-ZSTD clevel=3
│   fill   = NaN
├── derived/                    # watertable_elevation, watertable_depth,
│   ├── watertable_elevation   #   seepage_areas, etc.
│   ├── watertable_depth       # écrits seulement si pré-calculés ; sinon
│   └── seepage_areas          # virtual_fields.py les calcule à la volée
├── budget/                     # DRN, RCH, WEL spatial fields
│   ├── drn
│   ├── rch
│   └── …
├── pathlines/                  # particle trajectories (Modpath)
├── geographic/                 # rasters (DEM, geology, …)
│   └── <name>.zattrs: transform[6], crs, nodata, shape
└── forcing/                    # input forcings persisted for provenance
    └── <variable>/
        ├── <station_id>/
        │   ├── timestamps     (n,)   int64 view of datetime64[ns]
        │   ├── values         (n,)   float64
        │   └── .zattrs        unit, source, n_records
        └── <static_variable>   direct array + attrs
```

### 3.1 Chunking

Chunking actuel (`zarr_store.py:129-133`) :

```python
# cas 1D (n_timesteps, n_cells):
chunk_shape = (1, n_cells)
# cas 2D (n_timesteps, n_layers, n_cells):
chunk_shape = (1, n_layers, n_cells)
```

→ **un chunk = une snapshot complète de tout le maillage**.

| Pattern d'accès | Lecture requise | Verdict |
|---|---|---|
| Carte à un instant (`field(var, t=42)`) | 1 chunk (optimal) | **conforme** |
| Timeseries à un point (`ts(var, cell_id=123)`) | **n_timesteps chunks** à décompresser entièrement pour extraire 1 cellule | **problématique** |
| Découpe temporelle (1 mois sur tout le domaine) | 30 chunks (OK) | **acceptable** |
| Accès 3D cube (une coupe 2D à travers les layers) | 1 chunk | **conforme** |

Pour `n_cells = 100 000, n_layers = 3, n_timesteps = 3 650` (10 ans journaliers) :

- 1 chunk ≈ 100 000 × 3 × 8 o = **2.4 MB décompressé** (≈ 200 KB après ZSTD
  sur un champ lisse). Correct pour Zarr (recommandation : 1-50 MB).
- Timeseries à un point = **3 650 chunks** = 730 MB à décompresser pour lire
  29 KB de données utiles. **3 ordres de grandeur de sur-lecture**.

**Comparaison industrie** :
- xarray + dask recommande un chunking **bi-temporel** : `(chunk_t, n_layers, chunk_c)`
  où `chunk_t × chunk_c × 8o ≈ 10 MB`. Pour n_cells=100 000, n_t=3650 : chunks
  `(365, 3, 10000)` = 87 MB → un poil gros. Ajuster à `(180, 3, 5000)` ≈ 21 MB.
- ERA5 / Pangeo chunke typiquement à `(168 h, N_lat, N_lon)` soit environ 20 MB.

**Verdict** : **à améliorer**. Le chunking `(1, n_layers, n_cells)` est un choix
**expédient** (permet d'écrire chunk-par-chunk dans la boucle timestep) mais
ne tient pas compte des patterns de lecture. Les accès timeseries (très
fréquents pour le diagnostic hydrologique — piézomètres, séries à l'exutoire)
seront **drastiquement** sous-optimaux.

**Recommandation** :

1. Choisir `chunk_t` et `chunk_c` tels que `chunk_t × n_layers × chunk_c × 8o ≈ 16 MB`.
   Écrire par blocs temporels (buffer de 128-365 timesteps).
2. Exposer `chunk_strategy` dans `ResultsConfig` : `"map"` (actuel) vs
   `"timeseries"` vs `"balanced"`.
3. Pour les simulations avec beaucoup de stations, matérialiser les timeseries
   aux points d'observation directement en DuckDB (déjà fait — `timeseries`
   table) et ne pas lire le Zarr pour ces points.

### 3.2 Compression BLOSC-ZSTD clevel=3

| Paramètre | Valeur | Verdict |
|---|---|---|
| Codec | BLOSC-ZSTD | **conforme** — standard cloud (ERA5, Pangeo) |
| clevel | 3 | **acceptable** — clevel=3 est le sweet spot ZSTD (ratio/vitesse). Pas ajustable par variable. |
| shuffle | **non spécifié** | **à améliorer** — `BloscShuffle.shuffle` active le byte-shuffle qui améliore de 20-40 % le ratio sur les float64 lisses. Non utilisé ici. |
| Codec per variable | Identique partout | **à améliorer** — `seepage_areas` (binaire 0/1) serait mieux avec un entier + RLE ou un `VarLenBytes` bitpack. |

**Verdict** : **conforme avec réserves**. BLOSC-ZSTD clevel=3 est le défaut
recommandé par **zarr-specs v3** et **Pangeo**. Activer le byte-shuffle sur
les floats (`BloscShuffle.shuffle` en Zarr v3) est un gain gratuit.

### 3.3 Zarr v2 vs v3

Le code utilise **v3** (`zarr.codecs.BloscCodec`, `LocalStore`, `ZipStore`
v3 API). Conséquences :

| Outil | Compat Zarr v3 (avril 2026) |
|---|---|
| `xarray` | OK (≥ 2024.11) |
| `zarr-python` | OK (≥ 3.0) |
| `QGIS` MDAL driver | **NON** — ne lit que v2 |
| `Panoply` NASA | **NON** — ne lit que v2 |
| `ParaView` | **NON** (via VTK-Zarr qui stagne en v2) |
| `Google Cloud Storage Fuse` | OK |

**Verdict** : **à améliorer**. Choisir v3 est un pari sur l'avenir. Pour un
outil dont un des buts affichés est l'interopérabilité (cf. conventions CF +
UGRID), **cela ferme la porte à QGIS et ParaView pendant 12-24 mois**. Le code
de `open_group` accepte les deux versions (zarr-python peut être configuré
pour produire du v2), donc c'est un choix délibéré invisible.

**Recommandation** : documenter ce choix, exposer `zarr_format: 2 | 3` dans
`ResultsConfig`, par défaut `2` jusqu'à ce que QGIS/ParaView suivent.

### 3.4 Metadata CF

**Aucune attribut CF sur les arrays Zarr** : pas de `standard_name`, `units`,
`long_name`, `_FillValue`, `valid_range`, `cell_methods`, `grid_mapping`.

Ce qu'un champ `head` devrait avoir (CF-1.8) :

```python
head.attrs = {
    "standard_name": "water_table_elevation",  # ou "groundwater_head"
    "long_name": "Hydraulic head",
    "units": "m",
    "_FillValue": np.nan,
    "cell_methods": "time: point area: mean",
    "grid_mapping": "crs",
}
```

Ce qu'il y a actuellement : rien (sauf `n_cells`, `n_layers` au niveau root).

**Verdict** : **à améliorer**. L'absence de conventions CF sur les fichiers
Zarr rend les données **auto-descriptives = non**. Un consommateur externe
(xarray) doit deviner les unités.

---

## 4. Exporters

### 4.1 NetCDF (`exporters/netcdf.py`)

| Critère | Verdict | Détail |
|---|---|---|
| UGRID-1.0 mesh topology | **conforme** | `cf_role`, `topology_dimension`, `face_node_connectivity`, `_FillValue=-1` OK |
| CF-1.8 `Conventions` attribute | **acceptable** | Présent (`"UGRID-1.0"`) mais devrait être `"CF-1.8, UGRID-1.0"` |
| `standard_name` sur variables | **problématique** | Absent — aucun standard name |
| `units` sur variables | **problématique** | Absent |
| `grid_mapping` (CRS) | **problématique** | Absent — le fichier ne dit pas en quelle projection sont `node_x`/`node_y` |
| `time` CF (`units: "days since 2000-01-01"`, `calendar: "standard"`) | **problématique** | `units="timestep index"` — c'est un compteur, pas du temps CF |
| `_FillValue` sur champs | **à améliorer** | Absent sur les variables de données (présent uniquement sur `face_nodes`) |
| Lisibilité par QGIS (MDAL) | **à améliorer** | Partiellement ; MDAL cherche `time:standard_name="time"` qui manque |
| Lisibilité par THREDDS | **problématique** | Sans CRS, inutilisable en catalog geo |
| Lisibilité par ncview/Panoply | **acceptable** | UGRID affichera la topologie |

**Verdict** : **à améliorer**. Le NetCDF est UGRID-compatible structurellement,
mais **pas CF-1.8**. Un fichier non-CF ne sera pas ingéré par la plupart des
pipelines scientifiques.

**Recommandation** :

```python
ds.attrs["Conventions"] = "CF-1.8, UGRID-1.0"
ds["crs"] = xr.DataArray(0, attrs={
    "grid_mapping_name": "lambert_conformal_conic",  # pour EPSG:2154
    "epsg_code": "EPSG:2154",
    "crs_wkt": "...",
})
ds["time"].attrs = {
    "standard_name": "time",
    "long_name": "time",
    "units": f"days since {period_start}",
    "calendar": "standard",
}
ds["head"].attrs = {
    "standard_name": "water_table_elevation",
    "units": "m",
    "grid_mapping": "crs",
    "mesh": "mesh2d",
    "location": "face",
    "_FillValue": np.float64(1e20),
}
```

### 4.2 VTU (`exporters/vtu.py`)

**Bug critique** :

```python
# exporters/vtu.py:97-105
tri_mask = (connectivity[:, 3] == -1) if max_vpf >= 4 else ...
quad_mask = ~tri_mask

cells = []
if tri_mask.any():
    cells.append(meshio.CellBlock("triangle", connectivity[tri_mask, :3]))
if quad_mask.any():
    cells.append(meshio.CellBlock("quad", connectivity[quad_mask, :4]))
```

Puis :

```python
# exporters/vtu.py:108-115
def _split_cell_data(data: np.ndarray, cells: list) -> list[np.ndarray]:
    result = []
    offset = 0
    for block in cells:
        n = block.data.shape[0]
        result.append(data[offset:offset + n])   # ☠ BUG
        offset += n
    return result
```

**Problème** : `_split_cell_data` prend les `n` premiers éléments de `data`
puis les `m` suivants, alors que les blocs `cells` ont été construits par
**masquage** (non contigu). Les indices cellulaires dans `connectivity[tri_mask]`
ne sont **pas** les `n` premiers de `connectivity` — sauf si le mesh est trié
triangles-puis-quads, ce qui n'est garanti par rien.

**Conséquence** : si un mesh mixte (certains cells tri, d'autres quad dans un
ordre arbitraire — c'est le cas de gmsh + contraintes), **les valeurs de champ
sont associées aux mauvaises cellules dans ParaView**.

**Fix** :

```python
def _split_cell_data(data, tri_mask, quad_mask):
    parts = []
    if tri_mask.any():
        parts.append(data[tri_mask])
    if quad_mask.any():
        parts.append(data[quad_mask])
    return parts
```

**Verdict** : **problématique** — bug silencieux. Vu la criticité, devrait
être couvert par un test de régression unitaire. L'absence de tests unit pour
`exporters/` (vérifié : `tests/unit/` ne contient pas `results/exporters/`)
rend cette classe de bug invisible.

### 4.3 GeoTIFF (`exporters/geotiff.py`)

| Critère | Verdict | Détail |
|---|---|---|
| `driver="GTiff"` | **conforme** | |
| `crs` renseigné | **acceptable** | Paramètre `crs="EPSG:2154"` codé en dur par défaut ; devrait être lu depuis `simulations.crs` |
| `nodata` renseigné | **conforme** | `-9999.0` |
| `transform` géoréférencé | **conforme** | `from_bounds` OK |
| `dtype="float64"` | **à améliorer** | Double la taille vs float32 ; pas de test si la précision le justifie |
| Multi-bands (layer/timestep) | **non-standard** | 1 seule bande ; il faudrait `count=n_layers` ou un fichier par timestep |
| `band.description` | **problématique** | Absent ; une bande « head à t=42 » n'est pas labellisée |
| `tags` / `metadata` | **problématique** | Aucune tag GDAL (`AREA_OR_POINT`, `TIFFTAG_DATETIME`, `TIFFTAG_SOFTWARE`) |
| Compression LZW/DEFLATE | **à améliorer** | Pas activée ; GeoTIFF non compressé 3-5× plus gros |
| Tiling | **à améliorer** | Pas de `tiled=True` ; préjudicie le cloud-optimized (COG) |

**Verdict** : **acceptable** pour un export minimal, mais **pas Cloud-Optimized
GeoTIFF** (COG). Un export pour QGIS local marchera ; un export destiné à
S3/STAC ne sera pas streamable efficacement.

**Recommandation** : ajouter `compress="lzw"`, `tiled=True, blockxsize=256,
blockysize=256`, et remplacer `resolution=100.0` par une auto-détection basée
sur la taille de maille médiane.

### 4.4 Shapefile (`exporters/shapefile.py`)

**Verdict** : **problématique**.

- **Format obsolète** (années 90, ESRI). Shapefile a 5 limitations structurelles :
  - Noms de colonnes **limités à 10 caractères** (DBF). `geopandas` tronque
    silencieusement ; ici `variable` peut être `"watertable_elevation"` (20
    chars) → exporté en `"watertable"` avec collision possible.
  - Types DBF pauvres (pas de datetime natif, pas de bool).
  - Pas d'UTF-8 garanti (encoding CPG, erratique).
  - Limite 2 GB.
  - Géométries multi-part fragiles.
- **GeoPackage (GPKG)** est le successeur standard (OGC) depuis 2014. Basé sur
  SQLite, plus robuste, tout schéma, date+heure, UTF-8.
- Pas de `.prj` explicitement écrit (geopandas le fait mais sans garantie si
  `crs=None`).

**Recommandation** : remplacer par GeoPackage. Ou exposer les deux (`fmt="gpkg"`
par défaut, `fmt="shp"` en legacy).

### 4.5 CSV (`exporters/csv.py`)

| Critère | Verdict | Détail |
|---|---|---|
| Header présent | **acceptable** | `datetime, station_id, variable, value, unit` |
| Unités dans colonnes | **à améliorer** | Colonne `unit` OK ; mais une ligne par (point, variable, temps) = format long non idiomatique pour consommateurs Excel |
| Séparateur | **conforme** | virgule |
| Quoting | **acceptable** | défaut pandas |
| Datetime format ISO-8601 | **acceptable** | dépend de pandas (OK) |
| Métadonnées (sim_id, software version, created_at) | **problématique** | **Absentes** — le CSV n'est pas auto-descriptif |
| Format large vs long | **à améliorer** | Format long imposé ; un `pivot()` préalable serait utile pour Excel |

**Comparaison industrie** : les CSV scientifiques incluent généralement un
préambule type **Frictionless Data Package** (`datapackage.json`) ou un
header commenté `# sim_id: ...` `# created_at: ...` (CAMELS, GRDC, SHEF).

**Verdict** : **à améliorer**. Ajouter un préambule commenté (`# `) ou
co-générer un `.json` sidecar avec les métadonnées.

### 4.6 Duplication dans les exporters

La fonction `_find_variable` apparaît **4 fois à l'identique** :

- `exporters/netcdf.py:147-155`
- `exporters/geotiff.py:129-137`
- `exporters/vtu.py:119-127`
- `exporters/shapefile.py:95-103`

Idem pour la logique de chargement mesh (`mesh = grp["mesh"]`, `vertices = mesh["vertices"][:]`,
`connectivity = mesh["face_node_connectivity"][:]`) dupliquée dans les 4 fichiers.

**Verdict** : **à améliorer** (duplication évidente).

**Recommandation** : extraire dans `exporters/_mesh_loader.py` :

```python
def load_mesh_and_variable(zarr_path, variable, timestep, *, layer=None):
    root = zarr.open_group(str(zarr_path), mode="r")
    mesh = root["mesh"]
    return {
        "vertices": mesh["vertices"][:],
        "connectivity": mesh["face_node_connectivity"][:],
        "data": _find_variable(root, variable)[timestep],
        ...
    }
```

Économie : ~40 lignes sur 522 lignes d'exporters (~8 %).

---

## 5. Provenance

### 5.1 Ce qui est fait (`provenance.py`, `catalog.py:write_provenance`)

```python
fp = {
    "checksum": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    "shape": list(data.shape),
    "dtype": str(data.dtype),
    "stats": {"mean": ..., "min": ..., "max": ..., "std": ...},
}
```

Inséré dans la table `provenance(sim_id, variable, source_type, source_ref,
checksum, period_start, period_end, n_records, stats)`.

### 5.2 Comparaison avec les standards

| Standard | Concept | HydroModPy | Verdict |
|---|---|---|---|
| **W3C PROV-O** | Triplet `(Entity, Activity, Agent)` | Juste `Entity` (le fichier d'entrée) | **incomplet** |
| **PROV** `wasDerivedFrom` | Chaîne parent→enfant | `simulations.parent_sim_id` existe mais pas lié à `provenance` | **partiel** |
| **PROV** `wasAttributedTo` (utilisateur) | Qui a lancé la sim ? | Aucun champ user/host/process | **absent** |
| **DVC** | Hash de fichiers + DVC.yaml + Git | SHA-256 sur `tobytes()` (contenu post-parsing, **pas le fichier brut**) | **moins bon** |
| **MLflow Tracking** | params + metrics + artifacts + env | params ✓, metrics ✓, artifacts ≈ (zarr), env ✗ | **partiel** |
| **RO-Crate (Research Object)** | JSON-LD + fichiers | Aucun | **absent** |
| **FAIR principles** | Findable, Accessible, Interoperable, Reusable | DOI absent, versioning schéma absent, licence dans metadata absent | **faible** |

### 5.3 Problèmes concrets

1. **Le checksum est calculé sur `tobytes()` d'un numpy array post-ingestion** :
   `hashlib.sha256(contiguous.tobytes())`. Deux problèmes :
   - Dépend du **dtype** (float32 vs float64 sur la même donnée → hash différent).
   - Ne correspond **pas** au hash du fichier source (GeoTIFF, NetCDF). Impossible
     de vérifier « le fichier sur disque est-il celui utilisé ? ».
   - Solution industrie : hasher **à la fois** le fichier source (SHA-256 octet-à-octet)
     **et** l'array ingéré (pour détecter un bug d'ingestion silencieux). Les
     deux sont utiles mais différents.
2. `source_ref` est juste un `VARCHAR` — pas de distinction URI/path/UUID.
3. `n_records = np.prod(shape)` est le nombre **d'éléments** du tableau, pas
   le nombre de records temporels. Ambigu.
4. Pas de timestamp `fetched_at` ni d'identifiant de version du data manager
   qui a produit la donnée.
5. Pas de lien explicite entre `provenance` et la table `data/cache.duckdb`
   (où les hashes des fichiers sources pourraient être stockés).
6. Pas de signature numérique ni de `manifest.json` dans le `.hmp`.

**Verdict** : **à améliorer**. Le tracking est une **traçabilité statistique**
(détecte si la donnée a changé) mais pas une **provenance scientifique**
complète. Pour publier un résultat reproductible, il manque : user, host,
Python version, HydroModPy version, solver binary hash, timestamp précis, URI
source originale.

**Recommandation** : ajouter une table `run_environment` :

```sql
CREATE TABLE run_environment (
    sim_id       UUID PRIMARY KEY,
    user_id      VARCHAR,
    hostname     VARCHAR,
    python_ver   VARCHAR,
    hmp_version  VARCHAR,
    git_sha      VARCHAR,
    solver_binary_sha VARCHAR,
    pip_freeze   JSON,
    started_at   TIMESTAMPTZ,
    ended_at     TIMESTAMPTZ
);
```

---

## 6. Interopérabilité

Question clef : un utilisateur peut-il ouvrir les résultats **sans** passer par
l'API HydroModPy ?

### 6.1 Test d'ouverture directe

| Outil | Cible | Fonctionne en 2026 ? | Blocker |
|---|---|---|---|
| `duckdb-cli` ou Python `duckdb.connect("hydromodpy.duckdb")` | Tables metadata | **oui** | aucun |
| `pd.read_sql("SELECT ...", ...)` via DuckDB | idem | **oui** | aucun |
| `xarray.open_dataset("sim.zarr", engine="zarr")` | Champs spatiaux | **partiellement** | Zarr v3 + absence de metadata CF → l'utilisateur voit `head(time, layer, cell)` sans unités ni coordonnées physiques |
| `xarray.open_dataset("sim.zarr")` + xugrid | UGRID | **partiellement** | `xugrid` lit UGRID-NetCDF, pas UGRID-Zarr (pas de convention officielle) |
| `QGIS → Add Mesh Layer` sur `.nc` exporté | Carte head | **oui si NetCDF exporté**, pas directement sur Zarr v3 | voir 4.1 : manque CF complet |
| `ParaView → Open` sur `.vtu` exporté | 3D | **oui**, mais bug `_split_cell_data` si mesh mixte | voir 4.2 |
| QGIS Shapefile | Polygones | **oui** | troncature noms |
| QGIS GeoTIFF | Raster | **oui** | OK |
| **Accès direct au `.zarr.zip`** depuis un pipeline tiers | Champs | **NON** | ZipStore en mode `mode="r"` seulement ; stockage opaque pour un non-initié |

### 6.2 Problèmes d'interop

1. **Zarr v3 + zip + pas de CF** = conteneur opaque. Seule l'API HydroModPy sait
   lire correctement.
2. **Pas de sidecar `manifest.json`** qui documenterait ce qui est dans le Zarr.
3. Les paths absolus (`zarr_path = "simulations/<uuid>.zarr.zip"`) sont
   enregistrés **relativement au workspace**. Si on copie la DuckDB sans le
   zarr, cohérence perdue silencieusement (aucune erreur tant qu'on ne touche
   pas aux champs).
4. Pas d'export **tout-en-un** `sim_id` → NetCDF + GeoPackage dans un dossier
   avec `README.md` généré (ce serait l'archive la plus portable).

**Verdict** : **à améliorer**. L'API HydroModPy est nécessaire pour une
utilisation complète ; sans l'API, on peut toujours lire les **exports**
(NetCDF/CSV/GeoTIFF) mais **pas le stockage primaire** de manière standard.
Le Zarr ne contient pas assez de metadata pour être self-describing.

---

## 7. Concurrence

### 7.1 DuckDB : règles de concurrence

DuckDB 0.10+ supporte :
- **1 writer + N readers simultanés** sur la même base (mode par défaut).
- Pas de 2 writers simultanés — la 2e connexion obtiendra une erreur.
- Pas de `BEGIN IMMEDIATE` / `BEGIN EXCLUSIVE` explicite dans `catalog.py`.

### 7.2 Ce que fait le code

Toutes les écritures dans `catalog.py` passent par `self._db` (`duckdb.connect(...)`).
`register_simulation`, `write_parameters`, `write_timeseries`, etc. sont des
`INSERT` directs.

**Transactions explicites** : uniquement dans `delete()` (`catalog.py:896-904`)
et `import_simulation()` (`catalog.py:815-842`). Tout le reste est en
auto-commit.

**Locks** : aucune synchronisation applicative (pas de `filelock`, pas de
`fcntl`). Le code suppose une seule instance de `SimulationCatalog` par
workspace.

### 7.3 Scénarios pathologiques

| Scénario | Effet |
|---|---|
| 2 processes `hmp run` sur le même workspace | **Crash** — le 2e `duckdb.connect()` lève `IOException: Could not set lock on file` |
| 1 process HydroModPy + `duckdb-cli` ouvert en lecture | **OK** en DuckDB 0.10+ (read-only possible) |
| `hmp run` crash après INSERT partiel (batch calibration) | **Risque de ligne orpheline** — `register_simulation` est auto-committed, pas de rollback si le run meurt ensuite |
| 2 `write_timeseries` rapides sur même sim_id/station | **Doublons** (pas de PK) |
| SIGKILL pendant `finalize()` | **État inconsistant** — status reste `running`, zarr peut être à moitié zippé. Pas de journal de recovery. |

**Verdict** : **problématique** pour un usage HPC / cluster / pipelines parallèles.
Acceptable pour un usage mono-user desktop, qui est visiblement la cible actuelle.

**Recommandation** :

1. Documenter que **le workspace est mono-writer** (dans le README).
2. Ajouter un `filelock` en début de `__init__` pour lever une erreur claire :
   ```python
   from filelock import FileLock, Timeout
   self._lock = FileLock(self._db_path.with_suffix(".duckdb.lock"))
   try:
       self._lock.acquire(timeout=5)
   except Timeout:
       raise RuntimeError(f"Workspace {workspace_path} is locked by another process")
   ```
3. Pour la calibration batch (qui lance N sims), passer par **une seule instance
   de `SimulationCatalog` partagée** avec des workers qui envoient les données
   via IPC (queue), pas en ouvrant N connections.
4. Ajouter un garde `try/except` global dans les launchers pour finaliser en
   `status="failed"` plutôt que `status="running"` zombie.

---

## 8. Format `.hmp` (package portable)

### 8.1 Structure

D'après `catalog.py:export_simulation:738-781` et `import_simulation:783-859` :

```
<output>/
├── simulation.duckdb    # base DuckDB restreinte à 1 sim (12 tables per-sim + simulations)
├── results.zarr.zip     # ou results.zarr/ (directory legacy)
```

Pas d'extension `.hmp` reconnue — c'est **un dossier**, pas une archive. La
doc CLAUDE.md mentionne `"run.hmp"` mais le code écrit un **répertoire**.

### 8.2 Problèmes

| Problème | Gravité |
|---|---|
| **Pas un format** : juste un dossier de 2 fichiers, aucune archive (`.tar.gz`, `.zip`) | Moyen — pas pratique à partager par email |
| **Pas de versioning d'export** : pas de `manifest.json { "format_version": 1, "exporter": "hmp 0.x" }` | Élevé — un `.hmp` produit en 2026 ne pourra être relu en 2030 si le schéma a changé |
| **Bug `import_simulation`** (`catalog.py:831-838`) : | Élevé |

```python
if pkg_zarr_zip.exists():
    zarr_path = f"simulations/{sid}.zarr.zip"
else:
    zarr_path = f"simulations/{sid}.zarr.zip"   # ☠ LIGNE IDENTIQUE
```

Les deux branches sont identiques. Du dead code visible. L'intention était
probablement `f"simulations/{sid}.zarr"` dans la branche else (directory
legacy), mais c'est remplacé ensuite dans la logique de copie.

| Problème | Gravité |
|---|---|
| Pas de `README.md` auto-généré ni de `manifest.json` dans le package | Moyen — un recevant n'a aucun contexte |
| Pas de signature / hash de vérification du package | Moyen — un .hmp peut être silencieusement corrompu en transit |
| Pas de test de round-trip (`export → import`) dans `tests/unit/results/` | Élevé — bug connu ci-dessus non attrapé |
| **Réserve le nom `simulations/<uuid>.zarr.zip`** à l'import, peu importe le nom d'origine | Faible |

**Verdict** : **problématique**. Un format d'échange doit être (a) un **fichier
unique** (archive), (b) **versionné**, (c) **auto-décrit** (manifest), (d)
**testé en round-trip**. Ici : aucun des 4.

**Recommandation** :

1. Empaqueter en **un seul `.hmp` qui est un zip** (convention ROCrate) :
   ```
   my_run.hmp  (= zip)
   ├── manifest.json        { "format_version": 1, "sim_id": "...", "hmp_version": "0.x", "exported_at": "..." }
   ├── simulation.duckdb
   ├── results.zarr.zip
   └── README.md            # auto-généré avec metadata & comment lire
   ```
2. Versionner `format_version` indépendamment de `_schema_version` DuckDB.
3. Vérifier en import : `format_version <= supported_format`.
4. Ajouter un test `test_hmp_roundtrip.py` : export → import → diff de tous
   les tables.
5. **Corriger le bug `if/else` identique**.

---

## 9. Analyses transverses

### 9.1 Dead code et stubs exposés

| Élément | Fichier | Verdict |
|---|---|---|
| `Simulation.rerun()` lève `NotImplementedError` après avoir construit un `HydroModPyConfig` | `simulation.py:222-263` | **dead code** — API publique qui ne marche pas ; le `project = Simulation.__new__(...)` précédent est inutile |
| `resample_timeseries()`, `resample_field()` | `resample.py` | **dead code** — fichier entier, 31 lignes, aucune implémentation |
| `display.py` stubs (`drainage_density`, `concentration_map`, `pathlines`) | `display.py:114-117, 139-141` | **placeholders** — acceptable si documenté, mais pas de test |
| `surface_top` attendu par `virtual_fields._get_surface_top` | `virtual_fields.py:18-28` | **pas cohérent** — `SimulationZarr.write_mesh` n'écrit pas `surface_top`. Fallback sur `z_interfaces[0]` silencieusement (valeur constante pour tout le domaine → faux). |

**Verdict** : **problématique**. Des APIs publiques qui soulèvent
`NotImplementedError` sont une pollution de surface.

**Recommandation** : supprimer `resample.py` et la méthode `rerun()` ; les
réintroduire quand implémentées.

### 9.2 Duplication

| Duplication | Fichiers | Impact |
|---|---|---|
| `_find_variable` (logique de recherche dans subgroups) | `exporters/{netcdf,vtu,geotiff,shapefile}.py` + `zarr_store.py:read_field` | 4 copies ; 1 original dans `zarr_store` déjà. |
| `write_budget` vs `write_budgets` | `catalog.py:192-224` | 2 APIs pour la même chose ; `write_budgets` est vectorisée ; conserver seulement celle-ci |
| `write_mass_balance` vs `write_mass_balances` | `catalog.py:228-265` | idem |
| Chargement mesh du zarr (`root["mesh"]`, `vertices[:]`, etc.) | `exporters/{netcdf,vtu,geotiff,shapefile}.py` | Répété 4× |
| `timeseries` query dans `catalog.query_timeseries` et `Simulation.timeseries` | `catalog.py:491-516` et `simulation.py:131-156` | Code quasi-identique, 25 lignes × 2 |

**Verdict** : **à améliorer**.

**Recommandation** : `Simulation.timeseries` devrait déléguer à
`self._catalog.query_timeseries(...)`. Économie : 20 lignes sans perte.

### 9.3 Verbosité / abstractions inutiles

| Cas | Fichier | Constat |
|---|---|---|
| `SimulationCatalog.workspace_path` **et** `SimulationCatalog.project_path` (alias) | `catalog.py:52-57` | Deux properties qui retournent la même chose |
| `SimulationCatalog.write_provenance` **alias** `record_provenance` | `catalog.py:312` | `record_provenance = write_provenance` — ligne de dead weight |
| `SimulationCatalog.open_zarr_group` délègue à `open_zarr().root` avec argument `mode` ignoré | `catalog.py:437-438` | Paramètre `mode: str = "r"` inutile (ignoré), wrapper à 1 ligne |
| `Simulation.plot_all` try/except Exception large | `simulation.py:309-316` | Masque silencieusement les bugs de rendering |
| `SimulationGroup.parameters` et `SimulationGroup.metrics` | `simulation_group.py:49-86` | 2 × 20 lignes quasi-identiques (pivot). Factorisable. |

**Verdict** : **à améliorer**. Les 3 premiers points sont éliminables en 10 lignes.

### 9.4 Performance

| Point | Impact | Fix |
|---|---|---|
| `write_timeseries` utilise `np.full(n, ..., dtype=object)` 3× pour broadcaster `sim_id`/`station_id`/`variable`/`unit` | Copie inutile avant INSERT | Passer par `pd.DataFrame({"sim_id": sid, ...})` avec scalaire broadcasté ; ou INSERT VALUES en batch avec paramètres |
| `spatial_index.point_in_cell` construit un `Polygon` Python pour **chaque** cellule à chaque appel | O(n_cells) Python loop | Cacher l'STRtree dans le Zarr ou dans `SimulationZarr` |
| `virtual_fields._watertable_elevation` : boucle Python sur `n_layers` | Python loop au lieu d'une vectorisation `np.where`/`argmax` | `np.argmax(np.isfinite(head), axis=0)` + indexation |
| `exporters/geotiff.py` boucle Python sur toutes les faces pour construire shapes | 10-100k itérations | Vectoriser via `shapely.vectorized` ou construire via `shapely.creation.polygons` en bulk |
| `exporters/{vtu,shapefile,geotiff}.py` ne lit que 1 timestep mais fait `arr[timestep]` après avoir potentiellement chargé tout | Dépend du chunking | OK si chunk_t=1, mais si on rechunke pour timeseries, il faut ajuster |
| `catalog.export_simulation` fait une copie fichier par fichier via `shutil.copytree` | Linéaire | Acceptable |
| `cleanup()` boucle sur les rows et appelle `delete(sid)` un par un | O(n) transactions | `DELETE FROM ... WHERE sim_id IN (...)` en batch |

**Verdict** : **à améliorer** sur les points 1, 3, 4 (gains 5-50×). Le reste
est secondaire.

### 9.5 Gestion des erreurs

| Pattern | Fichier | Verdict |
|---|---|---|
| `try: ...; except Exception: logger.debug(...)` dans `finalize` (silencieux) | `catalog.py:886-887` | **problématique** — un échec de packing est logué en DEBUG donc invisible |
| Raise `KeyError` sans message structuré | Multiple | **acceptable** (messages courts OK) |
| Dans `plot_all` : `except Exception: logger.warning("Failed to render ...")` | `simulation.py:315-316` | **problématique** — masque Exception trop large |
| Pas de `logger.exception` avec stack trace | Partout | **à améliorer** |

### 9.6 Tests

```
tests/unit/results/        ← DIRECTORY ABSENT (vérifié via ls)
```

**Verdict** : **problématique**. Aucun test unitaire direct du module `results/`.
La couverture indirecte (via les tests d'extracteurs) est insuffisante pour
valider :

- Migrations de schéma
- Round-trip export/import `.hmp`
- Gestion de la concurrence
- Corrections des bugs identifiés (`_split_cell_data`, `import_simulation` if/else)

**Recommandation** : créer au minimum :
- `tests/unit/results/test_catalog_schema.py` (DDL, versioning)
- `tests/unit/results/test_zarr_store.py` (chunking, write/read roundtrip)
- `tests/unit/results/test_exporters.py` (un test par format, mesh mixte)
- `tests/unit/results/test_hmp_roundtrip.py`

---

## 10. Recommandations priorisées

### P0 — Bugs à corriger

1. **`exporters/vtu.py:_split_cell_data`** — bug silencieux pour mesh mixte
   tri/quad. Réécrire avec masques explicites. Ajouter test de régression.
2. **`catalog.py:import_simulation` if/else identique** (lignes 831-838). Soit
   corriger la logique pour gérer le cas directory, soit supprimer le `if`.
3. **`virtual_fields._get_surface_top`** : fallback silencieux à une valeur
   constante (`z_interfaces[0]`) produit un `watertable_depth` faux. Lever
   `KeyError` explicite si `surface_top` manque.

### P1 — Intégrité des données

4. **Ajouter PK** sur `timeseries`, `budgets`, `mass_balance`,
   `observation_points`, `provenance`. Empêche les doublons silencieux sur re-run.
5. **Ajouter FK** `sim_id → simulations(sim_id) ON DELETE CASCADE` sur les 9
   tables per-sim. Remplace le cleanup applicatif.
6. **Typer** `period_start` / `period_end` en `TIMESTAMP` (ou `DATE`), pas
   `VARCHAR`. Migrer les bases existantes.
7. **`created_at` / `timestamp`** en `TIMESTAMPTZ` (timezone-aware).

### P2 — Schéma de données

8. **Implémenter des migrations réelles** dans `MIGRATIONS` — test de upgrade
   depuis une base v1 snapshot.
9. **Ajouter une table `run_environment`** (user, host, hmp version, git sha,
   python version) pour traçabilité scientifique.
10. **Versionner le format `.hmp`** avec un `manifest.json` et empaqueter en zip.

### P3 — Interop & standards

11. **Compléter CF-1.8** dans `exporters/netcdf.py` : `standard_name`, `units`,
    `grid_mapping`, `time`.
12. **Attacher CF attrs aux arrays Zarr** (`units`, `standard_name`) — un
    consommateur xarray direct aura de la métadonnée.
13. **Remplacer Shapefile par GeoPackage** (ou les deux, GPKG par défaut).
14. **Cloud-Optimized GeoTIFF** : `tiled=True`, `compress="lzw"`.

### P4 — Refactorisations

15. Extraire `_find_variable` et chargement mesh dans `exporters/_common.py`.
16. Supprimer `resample.py`, `rerun()`, alias `record_provenance`,
    `project_path`, paramètre `mode` dans `open_zarr_group`.
17. `Simulation.timeseries` délègue à `catalog.query_timeseries`.
18. Supprimer `write_budget` (singleton) au profit de `write_budgets` (batch).

### P5 — Optimisations

19. Exposer `chunk_strategy` dans `ResultsConfig` : `"map"` | `"timeseries"` | `"balanced"`.
20. Vectoriser `_watertable_elevation` (`argmax`).
21. Activer `BloscShuffle.shuffle` pour gain 20-40 % sur les floats.
22. Décider Zarr v2 (portabilité) vs v3 (futur) et documenter.

---

## 11. Annexes — volumétrie du module

```
                   Fichier                   Lignes    % total    Commentaire
────────────────────────────────────────────────────────────────────────────
catalog.py                                      920     28.8%    ★ god-file à découper
zarr_store.py                                   323     10.1%
simulation.py                                   330     10.3%
catalog_schema.py                               280      8.8%
simulation_group.py                             178      5.6%
config.py                                       153      4.8%
exporters/netcdf.py                             155      4.9%
display.py                                      142      4.5%    duplique analysis/display
exporters/geotiff.py                            137      4.3%
exporters/vtu.py                                127      4.0%    bug
exporters/shapefile.py                          103      3.2%    format obsolète
virtual_fields.py                                97      3.0%
spatial_index.py                                 78      2.4%
exporters/csv.py                                 74      2.3%
provenance.py                                    59      1.9%
resample.py                                      31      1.0%    dead code
__init__.py / exporters/__init__.py               6      0.2%
─────────────────────────────────────────── ──────── ──────────
TOTAL                                         3 193      100%
```

`catalog.py` concentre **28.8 %** des lignes. Candidat à une découpe en :
- `catalog.py` : connexion + lifecycle (150-200 l.)
- `catalog_writes.py` : write_parameters/timeseries/budget/metric/provenance (300 l.)
- `catalog_queries.py` : query/list/find/best/latest (200 l.)
- `catalog_geographic.py` : geographic_feature/metadata/raster (150 l.)
- `catalog_package.py` : export_simulation / import_simulation (200 l.)

---

## Conclusion

Le package `results/` a les **bonnes intuitions** (DuckDB + Zarr, catalog
central, Pydantic config, exporters multi-format) mais l'exécution est à
**maturité intermédiaire**. Les choix techniques sont défendables ; la
**gouvernance des données** (PK, FK, migrations, typage) et la **qualité du
code** (duplication, dead code, bug silencieux VTU, bug import_simulation) le
sont moins.

Pour un outil qui se positionne comme un **catalogue de résultats scientifiques
reproductibles**, il manque les briques de provenance (PROV-O / run_environment),
de portabilité (format `.hmp` versionné) et de conformité (CF-1.8 complet).

**Verdict global : à améliorer**. Aucun élément n'est rédhibitoire pour un
usage mono-user, mais plusieurs sont bloquants pour un déploiement multi-user,
HPC, ou la publication FAIR de résultats hydrogéologiques.
