# TODO — ResultStore + Data Managers

> Plan d'implementation detaille pour les deux chantiers majeurs.
>
> **Documents de reference :**
> - ResultStore : [`hydromodpy/simulation/results/ARCHITECTURE.md`](../hydromodpy/simulation/results/ARCHITECTURE.md)
> - Data Managers : [`hydromodpy/data/structure.md`](../hydromodpy/data/structure.md)

---

## Etat actuel

| Module | Etat | Fichier(s) |
|--------|------|------------|
| `simulation/results/` | Vide (`__init__.py` vide + ARCHITECTURE.md) | — |
| `data/registry/catalog.py` | Complet, SQLAlchemy/SQLite (469 lignes) | `data/registry/catalog.py` |
| `data/contracts/` | Complets (PointRecord, FieldRecord, LoadResult, StationLocation) | `data/contracts/*.py` |
| `data/store.py` | Complet, facade DataStore (327 lignes) | `data/store.py` |
| `analysis/postprocess/` | Complet (runner + timeseries + netcdf + flow) | `analysis/postprocess/` |
| `analysis/display/` | Complet (suites, figures, adapters, post-hoc) | `analysis/display/` |
| Dependances | `zarr` et `duckdb` **absents** de `pyproject.toml` | `pyproject.toml` |

---

## Phase 0 — Fondations (prerequis)

### 0.1 — Dependances

- [ ] Ajouter `duckdb` dans `pyproject.toml`
- [ ] Ajouter `zarr>=3.0` dans `pyproject.toml`
- [ ] Ajouter `blosc2` dans `pyproject.toml` (via zarr)
- [ ] Ajouter `xugrid` en dependance optionnelle (export NetCDF/UGRID)
- [ ] `pip install -e .` — valider l'installation

### 0.2 — Enrichir les contracts existants

> Ref : `data/structure.md` §3 (LoadResult, PointRecord)

- [ ] `LoadResult` : ajouter `warnings: list[str] = field(default_factory=list)`
- [ ] `PointRecord` : ajouter `quality: dict | None = None`
- [ ] Integrer `compute_completeness()` (`common/validation.py`) dans `PointRecord.__post_init__`
- [ ] Tests unitaires contracts enrichis

---

## Phase 1 — ResultStore : coeur (DuckDB + Zarr)

> Ref : `simulation/results/ARCHITECTURE.md` §2, §5, §6, §7, §12

### 1.1 — Schema DuckDB (`simulation/results/schema.py`)

> Ref : ARCHITECTURE.md §6 — tables `project.duckdb` + `simulation_registry`

- [ ] Creer `schema.py`
- [ ] `create_project_tables(conn)` : 7 tables (`simulations`, `timeseries`, `budgets`, `metrics`, `observation_points`, `mass_balance_summary`, `input_provenance`)
- [ ] `create_registry_table(conn)` : table `simulation_registry` dans `catalog.duckdb`
- [ ] Index (`ix_registry_project`, `ix_registry_solver`, `ix_registry_status`, `ix_registry_created`)
- [ ] Tests : creation, idempotence, verification des colonnes

### 1.2 — Layout Zarr (`simulation/results/zarr_layout.py`)

> Ref : ARCHITECTURE.md §5 — layout `project_results.zarr/{sim_uuid}/`

- [ ] Creer `zarr_layout.py`
- [ ] `create_simulation_group(store, sim_id, mesh_info)` : groupes `mesh/`, `derived/`, `budget/`, `pathlines/`
- [ ] `write_mesh_arrays(group, hydro_mesh, z_interfaces)` : vertices, face_node_connectivity, z_interfaces, layer_indices, source_cell_indices + `.zattrs`
- [ ] `write_field_chunk(group, variable, timestep, values, chunks, compressor)` : ecriture d'un pas de temps dans un dataset 3D
- [ ] Chunking : `(1, nlayers, ncells)`, compression Blosc+Zstd clevel=3
- [ ] Tests : roundtrip ecriture/lecture, verification shapes et dtypes

### 1.3 — Provenance (`simulation/results/provenance.py`)

> Ref : ARCHITECTURE.md §4 (tracabilite des entrees)

- [ ] Creer `provenance.py`
- [ ] `fingerprint(data: np.ndarray) -> dict` : SHA-256 + stats (mean, min, max, std, shape, dtype)
- [ ] `verify_fingerprint(stored: dict, current: np.ndarray) -> bool`
- [ ] Tests unitaires

### 1.4 — Spatial index (`simulation/results/spatial_index.py`)

> Ref : ARCHITECTURE.md §15 (point-in-cell robustesse, shapely.STRtree)

- [ ] Creer `spatial_index.py`
- [ ] `point_in_cell(mesh_vertices, face_connectivity, points: dict) -> dict[str, int | None]`
- [ ] Utiliser `shapely.STRtree` sur les polygones des faces
- [ ] Retourner `None` + warning pour les points hors maillage
- [ ] Test avec un maillage triangulaire simple
- [ ] Test avec un maillage mixte tri/quad

### 1.5 — Classe ResultStore (`simulation/results/store.py`)

> Ref : ARCHITECTURE.md §7 — interface Python complete

Ordre d'implementation interne :

- [ ] Creer `store.py`
- [ ] `__init__(project_path, workspace_path=None)` : ouvre/cree `project.duckdb` + `project_results.zarr`, ATTACH optionnel `catalog.duckdb`

**Methodes d'ecriture :**

- [ ] `register_simulation(sim_id, config)` : INSERT dans `simulations`
- [ ] `finalize(sim_id, status)` : UPDATE status + duration, INSERT dans `simulation_registry` (si workspace)
- [ ] `write_mesh(sim_id, mesh, z_interfaces)` : ecrit topologie dans Zarr via `zarr_layout`
- [ ] `write_field(sim_id, variable, timestep, values)` : ecrit un champ dans Zarr
- [ ] `write_timeseries(sim_id, station, variable, ts)` : INSERT dans `timeseries`
- [ ] `write_budget(sim_id, timestep, zone, component, flux_in, flux_out)` : INSERT dans `budgets`
- [ ] `write_mass_balance(sim_id, timestep, total_in, total_out, percent_error)` : INSERT dans `mass_balance_summary`
- [ ] `record_provenance(sim_id, variable, source_ref, data)` : fingerprint + INSERT dans `input_provenance`
- [ ] `register_observation_points(sim_id, points, variable, layer)` : point-in-cell + INSERT

**Methodes de lecture :**

- [ ] `list_simulations(**filters)` : SELECT → pd.DataFrame
- [ ] `query_timeseries(sim_id, station, variable, period)` : lecture DuckDB → pd.Series
- [ ] `query_field(sim_id, variable, timestep, layer)` : lecture Zarr → np.ndarray
- [ ] `query_budget(sim_id, zone, period)` : SELECT → pd.DataFrame
- [ ] `query_mass_balance(sim_id)` : SELECT → pd.DataFrame
- [ ] `get_provenance(sim_id, variable)` : SELECT → pd.DataFrame
- [ ] `verify_provenance(sim_id, variable, current_data)` : compare hash
- [ ] `compare(sim_a, sim_b, variable, timestep)` : diff entre 2 sims

**Calibration :**

- [ ] `extract_calibration_vector(sim_id, observation_plan)` : vecteur 1D aligne sur les observations

**Export :**

- [ ] `export(sim_id, variable, format, path)` : dispatch vers les exporters (Phase 4)

**Suppression :**

- [ ] `delete_simulation(sim_id)` : DELETE dans project.duckdb (7 tables) + Zarr groupe + simulation_registry

**Concurrence :**

- [ ] Retry WAL + backoff exponentiel pour `catalog.duckdb` (ecriture concurrente)

**Tests :**

- [ ] Test cycle complet : register → write_mesh → write_field → finalize → query_field
- [ ] Test cycle timeseries : register → write_timeseries → query_timeseries
- [ ] Test delete_simulation (nettoyage 3 endroits)
- [ ] Test concurrence (2 finalize paralleles)

---

## Phase 2 — OutputAdapters (fichiers solver → ResultStore)

> Ref : ARCHITECTURE.md §8 — adaptateurs par solveur

### 2.1 — Base adapter (`simulation/results/adapters/base.py`)

- [ ] Creer `adapters/__init__.py`
- [ ] Creer `base.py`
- [ ] Protocole `BaseOutputAdapter` :
  - `phase1_extract(sim_id, solver_output_dir, store)`
  - `phase2_derived(sim_id, store, derived_config)`
  - `cleanup_solver_files(solver_output_dir, keep)`

### 2.2 — ModflowNwtOutputAdapter (`adapters/modflownwt.py`)

> Reutilise le code existant de `analysis/postprocess/flow/`

- [ ] Creer `modflownwt.py`
- [ ] Phase 1 : lire `.hds` (HeadFile), `.cbc` (CellBudgetFile), `.lst` (MfListBudget)
- [ ] Injecter dans ResultStore champ par champ (head, budget, mass_balance)
- [ ] Phase 2 : variables derivees (watertable_depth, seepage_areas, etc.)
- [ ] Tests avec fichiers MODFLOW-NWT de reference

### 2.3 — Modflow6OutputAdapter (`adapters/modflow6.py`)

- [ ] Creer `modflow6.py`
- [ ] Phase 1 : lire `.hds` (HeadFile MF6), `.cbc` (CellBudgetFile MF6), `.lst` (Mf6ListBudget)
- [ ] Phase 2 : variables derivees
- [ ] Tests avec fichiers MF6 de reference

### 2.4 — Mt3dmsOutputAdapter (`adapters/mt3dms.py`)

- [ ] Creer `mt3dms.py`
- [ ] Lire `.ucn` via `flopy.utils.UcnFile`
- [ ] Injecter concentration dans ResultStore

### 2.5 — ModpathOutputAdapter (`adapters/modpath.py`)

- [ ] Creer `modpath.py`
- [ ] Lire pathline/endpoint files
- [ ] Ecrire dans Zarr `pathlines/` (x, y, z, time)

### 2.6 — GR4JOutputAdapter (`adapters/gr4j.py`)

- [ ] Creer `gr4j.py`
- [ ] Resultats deja en memoire (pd.Series) → write_timeseries directement
- [ ] Pas de champs spatiaux (modele integre)

### 2.7 — Variables derivees (`adapters/derived.py`)

> Ref : ARCHITECTURE.md §8, table "Phase 2 — Variables derivees"

- [ ] Creer `derived.py`
- [ ] `watertable_elevation` : `flopy.utils.postprocessing.get_water_table(head)`
- [ ] `watertable_depth` : `SolverMesh.top - watertable_elevation`
- [ ] `seepage_areas` : `watertable_elevation >= SolverMesh.top` (booleen)
- [ ] `groundwater_flux` : magnitude des flux inter-cellules
- [ ] `accumulation_flux` : routage flux de drain sur reseau hydrographique
- [ ] `concentration_seepage` : concentration aux cellules de suintement
- [ ] `mass_seepage` / `mass_accumulated` : flux de masse au suintement
- [ ] Configurable via `[simulation.results.derived]` (TOML)

---

## Phase 3 — Migration catalogue SQLAlchemy → DuckDB

> Ref : `data/structure.md` §6 — catalogue DuckDB
> Ref : ARCHITECTURE.md §2 — DuckDB unifie

### 3.1 — Nouveau catalogue DuckDB (`data/registry/catalog_duckdb.py`)

- [ ] Creer `catalog_duckdb.py`
- [ ] Meme API que `DataCatalog` actuel
- [ ] Tables `entries` + `api_coverage` (schema identique + `fetch_metadata JSON`)
- [ ] `register()` : upsert par cle `(variable, source, station_id)` ou `(variable, source, file_path)`
- [ ] `find_cached()` : logique superset (bbox ET dates)
- [ ] `subsume_entries()` : nettoyage grilles redondantes
- [ ] `invalidate()` : suppression selective
- [ ] `cleanup()` : purge orphelins
- [ ] `list_entries()` : DataFrame audit
- [ ] Concurrence WAL + retry backoff
- [ ] Tests unitaires (miroir des tests existants du catalogue SQLAlchemy)

### 3.2 — Migration automatique SQLite → DuckDB

- [ ] Detecter `catalog.db` (SQLite) au premier lancement
- [ ] Migration via `ATTACH ... (TYPE SQLITE)` + `CREATE TABLE ... AS SELECT`
- [ ] Ajouter colonne `fetch_metadata` (absente de l'ancien schema)
- [ ] Test de migration avec un catalogue SQLite existant

### 3.3 — Bascule dans DataStore

- [ ] `data/store.py` : remplacer `DataCatalog` (SQLAlchemy) par `DataCatalogDuckDB`
- [ ] Supprimer `_FallbackDataCatalog` (DuckDB est embedded, pas besoin de fallback)
- [ ] Ajuster les imports dans tous les managers qui utilisent le catalogue
- [ ] Verifier que `DataStore.cache_info()` fonctionne toujours

### 3.4 — Tests de non-regression

- [ ] `pytest -m fast` : tous les tests rapides passent
- [ ] Comparer `find_cached()` ancien vs nouveau sur des cas reels
- [ ] Comparer `subsume_entries()` ancien vs nouveau
- [ ] Comparer `register()` ancien vs nouveau
- [ ] Test sur l'exemple 01_launcher (Canut) de bout en bout

### 3.5 — Nettoyage

- [ ] Supprimer `data/registry/catalog.py` (ancien SQLAlchemy)
- [ ] Supprimer `sqlalchemy` de `pyproject.toml`
- [ ] Supprimer les imports SQLAlchemy residuels
- [ ] Verifier qu'aucun code ne reference l'ancien catalogue

---

## Phase 4 — Exporters

> Ref : ARCHITECTURE.md §7 (methode export), §10 (config TOML), §12 (structure)

### 4.1 — Export NetCDF-4/UGRID (`simulation/results/exporters/netcdf.py`)

- [ ] Creer `exporters/__init__.py`
- [ ] Creer `netcdf.py`
- [ ] Zarr → xugrid → NetCDF-4/UGRID (topologie + champs)
- [ ] Compatible QGIS (MDAL), THREDDS
- [ ] Tests roundtrip

### 4.2 — Export CSV (`simulation/results/exporters/csv.py`)

- [ ] Creer `csv.py`
- [ ] DuckDB → pandas → CSV (series temporelles)
- [ ] Format : datetime, value, [station_id, variable]

### 4.3 — Export VTU (`simulation/results/exporters/vtu.py`)

- [ ] Creer `vtu.py`
- [ ] Zarr → meshio → VTU (pour ParaView / PyVista)

### 4.4 — Export GeoTIFF (`simulation/results/exporters/geotiff.py`)

- [ ] Creer `geotiff.py`
- [ ] Zarr → rasterisation maillage non-structure → GeoTIFF
- [ ] Via `rioxarray`

### 4.5 — Export Shapefile (`simulation/results/exporters/shapefile.py`)

- [ ] Creer `shapefile.py`
- [ ] Geometries des cellules + valeur a un timestep donne

---

## Phase 5 — Integration pipeline simulation

> Ref : ARCHITECTURE.md §9 (cycle de vie), §10 (config TOML), §13 (calibration)

### 5.1 — Brancher les OutputAdapters dans SimulationRunner

- [ ] Apres execution solver, appeler `OutputAdapter.phase1_extract()`
- [ ] Appeler `OutputAdapter.phase2_derived()` si configure
- [ ] Appeler `store.finalize()`
- [ ] Supprimer fichiers solver si `keep_solver_files = false`
- [ ] Appeler `store.record_provenance()` pour chaque forcage injecte

### 5.2 — Config Pydantic `[simulation.results]`

- [ ] Creer `ResultsConfig` (Pydantic) :
  - `store: bool = True`
  - `keep_solver_files: bool = False`
- [ ] `DerivedConfig` : flags par variable derivee (watertable_depth, seepage_areas, ...)
- [ ] `BudgetConfig` : `spatial_fields: bool = False`
- [ ] `ExportConfig` : `netcdf`, `csv_timeseries`, `vtu`, `geotiff`, `shapefile`, `output_dir`
- [ ] `ExportVariablesConfig` : `head`, `concentration`, `budget`, `pathlines`
- [ ] Integrer dans `HydroModPyConfig`

### 5.3 — Bridge calibration (`simulation/results/calibration_bridge.py`)

> Ref : ARCHITECTURE.md §13 — chemin chaud (RAM) vs chemin froid (store)

- [ ] Creer `calibration_bridge.py`
- [ ] `make_hot_simulator(run_fn)` : callback RAM-only pour la boucle de calibration
- [ ] `persist_calibration_result(store, result, run_fn)` : persiste le meilleur run
- [ ] Tests : verifier que le callback ne fait aucun I/O disque
- [ ] Tests : verifier que persist ecrit bien dans le store

---

## Phase 6 — Bascule des consommateurs + nettoyage

> Ref : ARCHITECTURE.md §14 — migration depuis le code existant

### 6.1 — Modifier `analysis/display/`

- [ ] Les suites lisent depuis `ResultStore` au lieu des `.npy` / CSV / post-hoc discovery
- [ ] `PosthocContext` utilise `ResultStore.list_simulations()` pour decouvrir les runs
- [ ] Les fonctions de rendering ne changent pas (recoivent pd.Series/DataFrame)
- [ ] Verifier que les figures sont identiques avant/apres

### 6.2 — Modifier `analysis/postprocess/`

- [ ] `PostprocessRunner` delegue aux OutputAdapters
- [ ] Les appels directs FloPy dans postprocess sont remplaces par des lectures ResultStore
- [ ] Verifier la non-regression sur les exports existants

### 6.3 — Nettoyage final

- [ ] Supprimer `analysis/postprocess/flow/` (remplace par `results/adapters/`)
- [ ] Supprimer `analysis/postprocess/netcdf/` (remplace par `results/exporters/netcdf.py`)
- [ ] Supprimer `analysis/postprocess/timeseries/` (remplace par `results/exporters/csv.py`)
- [ ] Supprimer pickle legacy `results_{model_name}.pkl`
- [ ] Supprimer dossier `_postprocess/` dans le workspace
- [ ] Supprimer `analysis/display/export_vtuvtk.py` (remplace par `results/exporters/vtu.py`)
- [ ] Mettre a jour `doc/22_results_store.md` et `doc/12_data_managers.md`
- [ ] Mettre a jour les fichiers `doc/` impactes (00, 16, 20, 21)

---

## Ordre de travail recommande

```
Phase 0  ── Fondations (dependances + contracts)         ~1 session
Phase 1  ── ResultStore coeur                             ~3-4 sessions
  1.1 schema → 1.2 zarr_layout → 1.3 provenance → 1.4 spatial_index → 1.5 store
Phase 2  ── OutputAdapters                                ~2-3 sessions
  2.1 base → 2.2 modflownwt → 2.3 modflow6 → 2.6 gr4j (prioritaires)
Phase 3  ── Migration SQLAlchemy → DuckDB                 ~2 sessions
  3.1 nouveau catalog → 3.2 migration → 3.3 bascule → 3.4 tests → 3.5 nettoyage
Phase 4  ── Exporters                                     ~1-2 sessions
Phase 5  ── Integration pipeline                          ~1-2 sessions
Phase 6  ── Bascule consommateurs + nettoyage             ~1-2 sessions
```

> **Recommandation** : demarrer par Phase 0 puis Phase 1.1 + 1.2 + 1.3
> (modules autonomes et testables independamment).
