# HydroModPy — carte du process (run, mesh, parallélisation, stockage)

Compagnon texte de l'artifact HTML `process-map`. Tout est basé uniquement sur `hydromodpy/`.
Chaque affirmation cite `fichier:fonction` (chemins relatifs à `hydromodpy/`). Termes techniques en
anglais, explications en français.

Sommaire :
1. Cycle de vie d'un run (12 steps)
2. Pipeline de maillage (DEM → D8 → Voronoi → DISV)
3. Parallélisation (API libmf6 vs subprocess mf6 exe)
4. Stockage & bases de données
5. Post-processing & extraction
6. Pièges & subtilités

---

## 1. Cycle de vie d'un run — les 12 steps

Entrée : `hmp.run` (`_api.py:run`) ou `Project.simulate` (`project/facade.py:Project.simulate`) →
`project/runner.py:ProjectRunner.run` → construit le plan (`workflow/steps/planning.py:step_build_plan`
→ `simulation/planning/planner.py:SimulationPlanner.build` → `SimulationPlan` de `ProcessRun`) puis
exécute un `Pipeline` (`workflow/runner.py:Pipeline`) des 12 `*Step` de
`workflow/orchestrator.py:standard_steps`.

Ordre (DAG Kahn `workflow/dag.py`, en pratique linéaire) :

```
validate → resolve → build_geographic → load_data → build_mesh → setup_process   [MODEL PHASE — une fois]
→ prepare_solver → run_solver → extract → derive → export → display               [RUN PHASE — par run/trial]
```

| Step | Classe (fichier) | Rôle |
|------|------------------|------|
| validate | `workflow/steps/validate.py:ValidateStep` | coerce le config racine en `HydroModPyConfig` |
| resolve | `workflow/steps/resolve.py:ResolveStep` | `WorkflowContext` + plan de load (`data.DataPlanner`) |
| build_geographic | `workflow/steps/setup.py:BuildGeographicStep` → `run_setup` | workspace, `CatchmentDelineation` (DEM/watershed/CRS), `Domain`, `run_id` |
| load_data | `workflow/steps/data.py:LoadDataStep` → `run_data` | `DataManagersRuntimeLoader.load_all` + **binder cascade** |
| build_mesh | `workflow/steps/mesh.py:BuildMeshStep` → `run_mesh_phase` | gmsh → `setup.mesh_planar` / `mesh_support` |
| setup_process | `workflow/steps/setup.py:SetupProcessStep` | `ensure_flow`/`ensure_transport` liés au domain |
| prepare_solver | `workflow/steps/prepare_solver/__init__.py:PrepareSolverStep` | catalog/persistence : `step_open_store` (sim_id, register, zarr time/crs/env, params/mesh/geographic, provenance, forcings) |
| run_solver | `workflow/steps/run_solver.py:RunSolverStep` → `SimulationRunner.execute` | **build + solve** (voir §3) |
| extract | `workflow/steps/extract.py:ExtractStep` | `post_run.extract_run_outputs` (raw → catalog) + `ingest_observations` |
| derive | `workflow/steps/derive.py:DeriveStep` | `derive_run_outputs` + `catchment_aggregation`, puis libère les modèles flopy |
| export | `workflow/steps/export.py:ExportStep` | gallery, `auto_export_results`, `.hmp`, `step_finalize_store` (close) |
| display | `workflow/steps/display.py:DisplayStep` | figures `[display]` |

**Deux surfaces d'orchestration** partageant les mêmes helpers `workflow.steps` :
- **Pipeline route** (canonique) : extract/derive/export sont des steps séparés ; `RunSolverStep`
  passe `after_run=None`.
- **Verb route** (`workflow/orchestrator.py:execute_run`) : post-processing inline dans
  `_after_run` → `post_run_results`. Utilisée pour l'itération notebook et la calibration.

### La binder cascade (`workflow/steps/data.py:apply_structural_updates_from_data`)

Rejouée à chaque override/sweep (sinon un forcing serait droppé). Ordre (helpers de
`physics/flow/structure_binders`) :

```
apply_geology_to_domain → ensure_flow → apply_oceanic_to_flow
→ apply_recharge_load_result_to_flow → apply_etp_load_result_to_flow
→ apply_lake_geometry_to_flow → apply_cutoff_wall_to_flow (voile) → apply_flow_barriers_to_flow
→ apply_lake_abacus_to_flow → apply_lake_bathymetry_to_flow → apply_lake_flux_forcings_to_flow
→ apply_runoff_to_sfr_networks (routed-first) → apply_lake_meteo_forcings_to_flow
→ attach_reference_hydrographic_network → bind_sfr_network_traces
```

### Calculé une fois vs reconstruit

- **Une fois (model phase, `run_setup` docstring)** : workspace, geographic (DEM/watershed/CRS), domain,
  `time_grid` (`project/phases.py`), `loaded_data` + cascade, mesh (`setup.mesh_planar/support/bundle`),
  `sfr_reach_traces`. Réutilisé via `is_prebuilt` + `model_phase_ready` (`project/runner.py`).
- **Par run/trial** : `SimulationPlan`, `sim_id` + ligne catalog (`step_open_store` mint `uuid4`),
  **tout le modèle MF6** (`build.py:run_pre_processing` : DISV + RCH/EVT/DRN/LAK/SFR/HFB/MVR/OC), le solve,
  l'extraction. (Le fast-path `reuse_solver_model` au niveau adapter est **désactivé** —
  `adapters/flow.py:execute` lève `NotImplementedError`, prouvé non output-équivalent.)

---

## 2. Pipeline de maillage — DEM → D8 → Voronoi → DISV

### 2.1 Preprocessing raster (WhiteboxTools, grid-independent, D8 uniquement)

Backend : facade `spatial/delineation/whitebox_workflows_backend` (`.raster`/`.flow`/`.delineation`,
un `wbw.WbEnvironment` partagé). Défaut `whitebox_workflows` (`spatial/delineation/registry.py:get_backend`).

```
DEM régional
 └ flow_products.build_regional_flow_products
    ├ fill/breach  → dem_correc      (WBT fill_depressions / breach_depressions_least_cost)
    ├ d8_pointer   → dem_direc.tif   (WBT d8_pointer, esri_pointer=False)
    └ d8_flow_accum→ dem_acc.tif     (WBT d8_flow_accum, out_type="cells")
```

- **Pas de D-infinity** : la direction de flow est D8 uniquement (`whitebox_workflows_backend/flow.py`).
- `build_regional_flow_products` retourne `FlowProducts` (correc/direc/acc), qui alimente le watershed,
  le réseau rivière et les traces SFR.

### 2.2 Réseau rivière + ordonnancement SFR

- `spatial/geographic/core/river_network.py:build_river_network_products` : threshold (area→cells) →
  `extract_streams` → strahler order → link id → vectorize → `RiverMeshTrace`. Garde des rasters
  **FULL DEM** (`*_full.tif`) car la délinéation SFR a besoin de l'affine non-clippé.
- `spatial/geographic/core/sfr_network.py:build_sfr_reach_trace_from_products` →
  `delineate_sfr_reaches` : groupe par link id, ordonne head→outlet en suivant le D8 pointer
  (`_order_link_cells`, `_downstream_cell`), tronque à la rive d'un lac (flag terminal-to-lake),
  résout le downstream + **Kahn topological sort** (`_topological_downstream_order`) → `ifno`
  downstream-increasing, tops monotones. Sortie `SfrReachTrace` (grid-independent). Le mapping sur les
  cellids DISV est **différé au builder** (§2.6).

### 2.3 Watershed & le "clip" de l'idomain (nuance importante)

- Polygone : `catchment_from_point.py:extract_catchment_from_point` (snap → watershed raster →
  vectorize → `watershed.shp`).
- **MAIS le DEM qui devient le top modèle est clippé à la box-buffer, pas au watershed** :
  `domain_dem.py:clip_dem_to_box_buffer` sur `box_buff` (bounding-box bufferisée, pas le polygone bassin).
- L'`inactive_mask`/idomain vient **uniquement du nodata DEM**
  (`solver/modflow_grid/discretization_spatial.py:_build_extruded_solver_mesh_from_runtime_planar`).
  Donc des cellules dans la box mais hors bassin **restent actives**. `domain_extent="watershed"` ne
  clippe pas par défaut (la frontière watershed est une contrainte de mesh optionnelle,
  `spatial/mesh/config/watershed.py`, `enabled=False`).

### 2.4 gmsh triangulation

`workflow/steps/mesh.py:run_mesh_phase` → `spatial/mesh/runtime_single_run.py` → pipeline conformal
`spatial/mesh/gmsh_grid/zone_meshing/conformal.py` → capture
`_gmsh_export.py:build_runtime_planar_mesh_from_gmsh` → `GmshPlanarMesh2D` (triangles, fixed-arity,
**refuse le ragged POLYGON**). Sizing = champs `Distance`+`Threshold` combinés par **`Min`**
(`_gmsh_fields.py`) ; raffinement lac/barrage `spatial/mesh/lake_refinement.py` (défaut off).

### 2.5 Voronoi dual (PEBI DISV) + choix `grid_dual`

`spatial/mesh/voronoi.py` :
- `voronoi_dual_of_mesh(planar_mesh, domain_polygon)` : seeds = sommets de la triangulation →
  `voronoi_planar_mesh`.
- `voronoi_cells` : `scipy.spatial.Voronoi`, `_finite_regions` (projette les ridges ouverts),
  **clipping concave** : intersect avec le domaine, garde le morceau qui **couvre la seed** (le centre
  DISV reste dans sa cellule), sinon le plus grand + `representative_point()`.
- Merge des sommets à `vertex_decimals=3`, `HydroMesh` ragged `CellType.POLYGON`, seeds stockées en
  `cell_data["disv_cell_center"]` (centres PEBI exacts écrits au DISV).
- **Choix** : `SolverSGridConfig.grid_dual` = `"voronoi"` (défaut) ou `"triangle"`. Appliqué dans
  `discretization_spatial.py:_build_extruded_solver_mesh_from_runtime_planar`. S'applique **uniquement à
  MF6-sur-gmsh** ; NWT structuré et Boussinesq gardent leur propre chemin.
- Voronoi = orthogonalité K exacte (TPFA, sans XT3D) car le centre DISV **est** la seed.

### 2.6 SolverMesh → flopy DIS/DISV + builders

- `solver/modflow_grid/solver_mesh.py:SolverMesh` : frozen dataclass **prismatic** (planar_mesh + top +
  botm + inactive_mask). `cell_centroids()` = `disv_cell_center` (seeds exactes).
  `to_disv_kwargs` → `spatial/mesh/adapters/flopy_adapter.py:to_flopy_disv_args` (oriente CW, xc/yc = centres).
- **Hétérogénéité** : `spatial/field/core/cell_sampling.py:sample_points_in_cell` ; POLYGON via
  `_polygon_points` (fan-triangulation, densité area-uniforme). `PolygonFieldMesh` wrappe le ragged
  POLYGON pour l'échantillonnage des champs (K/Sy/recharge) exactement comme les triangles.
- **Builders** (avant enregistrement DISV, reconstruisent un `flopy.VertexGrid` via
  `builders/vertex_grid.py:build_vertex_grid_for_intersection`) :
  - **LAK** (`builders/lake.py`) : `GridIntersect` polygons → CONNECTIONDATA VERTICAL (1 par colonne
    lac) + HORIZONTAL par edge partagé (`connwidth`=longueur edge, `connlen`=demi-distance CVFD exacte).
    Règle 1-lac-par-cellule (`_raise_on_shared_lake_cells`).
  - **SFR** (`builders/sfr.py`) : `GridIntersect` lines, **ordre le long de la ligne préservé**
    (`resolve_reach_line_cells`), Kahn re-sort → `ifno`, CONNECTIONDATA **signé**
    `[ifno]+[up…]+[-down…]` ; route vers LAK via `build_sfr_mover_records` (MVR SFR→LAK).
  - **HFB** (`builders/flow_barrier.py`) : PAS de GridIntersect ; consomme
    `spatial/mesh/flow_barrier.py:barrier_faces_from_line` (edges intérieurs traversés, `line.crosses`),
    HFB rows sur faces partagées, profondeur interpolée par vertex.
  - **MVR** (`builders/mvr.py`) : package-agnostic ; SFR→LAK, LAK→LAK/SFR (spillway), DRN→SFR/LAK.

---

## 3. Parallélisation — API (libmf6) vs subprocess (mf6 exe)

### 3.1 Fan-out des trials

`calibration/cli_runner.py:run_calibration_core` → `with api_isolation_context(use_api_isolation):
engine.run()` où `use_api_isolation = parallel > 1` (`cli_runner.py:_api_isolation_needed`).

`calibration/engine.py:CalibrationEngine.run` : boucle ask/tell (`batch_size` candidats par ask,
`parallel` = threads). `_evaluate_batch` :
- **serial** si `parallel <= 1` : list comprehension.
- **parallel** : `tasks = [(copy_context(), sugg) for sugg in suggestions]` puis
  `ThreadPoolExecutor(max_workers=min(parallel,len)).map(_run_in_context, tasks)` où
  `_run_in_context` fait `ctx.run(self._evaluate_with_cache, sugg)`.
- Threads (pas process) : l'evaluator ferme sur un `Project` vivant (DuckDB/Zarr non-picklables).
- `copy_context()` par tâche propage la scope api-isolation (ContextVar) aux workers.

### 3.2 Isolation par trial (`calibration/runners/trial.py` + `sandbox.py`)

**Dupliqué par trial** (`trial.py:fork`) : deep-copy config (`model_copy(deep=True)`) + params ;
shallow-copy setup (flow/transport remis à None) ; `WorkflowContext` frais ;
`ExecutionRegistry(lightweight=True)` ; `TrialSandbox` avec `model_name_override =
<base>_trialNNNNNN` → dossier scratch privé.

**Partagé par référence** : `domain`, `mesh_planar`, `geographic`, `time_grid`, `loaded_data`
(read-only), `sfr_reach_traces`, `base_cfg` (deep-copié par fork), `params_hash cache` (dict RAM).
Le catalog/DuckDB n'est touché que par le **main thread** (`persistence.append_iteration` dans le
callback `on_iteration`).

`_STRUCTURAL_BIND_LOCK` (`trial.py:65`) : sérialise **la seule phase de fork** (geology→domain,
lecture parquet lac, rebuild flow = GDAL/geopandas non thread-safe). Le solve tourne **hors du lock**.

**Cleanup RAII** : `TrialSandbox.__exit__` fait `rmtree` des dirs de sortie sauf si
`HMP_KEEP_TRIAL_SCRATCH`.

### 3.3 Sélection du runner (`solver/modflow_common/flow_adapter_helpers.py:_resolve_modflow_runner`)

`api` ⟺ (`_exposed_band_runoff_specs` présent, càd marnage) **OU** (`runtime.mf6_runner == "api"`).
Sinon `subprocess`. NWT et non-MF6 → toujours `subprocess`.

### 3.4 Chemin API (`solver/modflow6/run.py:_run_via_api`)

- Résout libmf6 (`ensure_solver_library`, honore `model.bin_path`), `_warn_mf6_version_parity`.
- Décision d'isolation : `if callback is None and api_isolation_enabled():` → `run_mf6_api_isolated`
  (spawn child) ; sinon in-process `run_mf6_api` (barre live). `api_isolation_enabled()` lit un
  **ContextVar** (`_api_isolation_var`, défaut False), posé par `api_isolation_context`.
- **Child isolé** (`api_subprocess.py:run_mf6_api_isolated`) : `mp.get_context("spawn")` (spawn
  obligatoire — un fork hériterait de la libmf6 déjà chargée) ; `result_queue` + `progress_queue` ;
  `_api_subprocess_entry` **rebuild le callback depuis les specs picklables** (`LakeBandRunoffSpec`),
  charge libmf6, silence le fd stdout ; timeout → `terminate()` + `SolverError`.
- Relais de progress : l'enfant poste `(completed, total)` par timestep ; le parent draine
  (`_drain_progress`) et rend une barre `Solving <trial>`.

### 3.5 Chemin subprocess (`run.py:run_processing`)

`run_simulation_with_progress(model.sim, nper)` (`modflow_common/progress.py`) → flopy
`sim.run_simulation` → **spawn le binaire `mf6` compilé** en un process OS. Progress = parse des lignes
stdout `"Solving: Stress period …"`. Pas de libmf6, pas de child Python.

### 3.6 Ce qui est dupliqué par process de solve

| Chemin | Nouveau process ? | Démarrage | Coût |
|--------|-------------------|-----------|------|
| subprocess exe | oui — binaire `mf6` natif | exécutable seul, pas de Python | le plus léger (~50-200 ms) |
| API in-process | non | libmf6.so chargé dans le parent | modéré, garde la barre live |
| API isolée | oui — spawn child Python | interpréteur + ré-import hydromodpy/modflowapi/xmipy + libmf6 + rebuild callback | le plus lourd (~2-5 s) |

Le compute (Newton) est **identique** ; l'API paie une taxe de spawn+imports+lib-load par solve,
acceptée seulement parce que libmf6 garde un état Fortran global non partageable entre threads.
**Skew moteur** : l'API résout avec libmf6, le subprocess + l'init steady-state avec l'exe ;
`binaries.py:warn_on_mf6_version_mismatch` alerte une fois si `major.minor` diffèrent.

---

## 4. Stockage & bases de données

Trois scopes DuckDB (jamais fusionnés) + Zarr + Parquet + sidecars + lock.

### 4.1 Les bases

| Base | Fichier | Owner | Contenu |
|------|---------|-------|---------|
| DATA | `<workspace>/data/cache.duckdb` | `data/registry/catalog_duckdb.py:DataCatalogDuckDB` | `entries` : DEM/meteo/recharge/geology (bbox, crs, sha256, file_path) |
| RESULTS | `<project>/catalog.duckdb` | `results/catalog/facade.py:Catalog` | `simulations`, `metrics`, `parameters`, `provenance`, `calibration_iterations(params_hash)`, `tracked_files`, `observations` |
| INDEX | `<state_dir>/index.duckdb` | `core/state/global_index.py:GlobalIndex` | machine-wide : `workspaces`→`projects`, `all_simulations` (fédération ATTACH r/o) + FTS |
| snapshot | `catalog_snapshot.duckdb` dans `.hmp` | `results/exporters/hmp_package.py` | export single-sim éphémère |

`params_hash` n'a **pas de fichier** : dict RAM (`calibration/cache.py:ParamsHashCache`), persisté comme
la colonne `calibration_iterations.params_hash` du RESULTS db.

### 4.2 Zarr (champs)

- Layout : `<project>/simulations/<project>__<id8>.zarr[.zip]` (`results/catalog/storage_paths.py`).
- Writer : `results/zarr_store/zarr_writer.py:write_field_stack` (via `SimulationZarr` /
  `WritesMixinZarr`, gated `save_zarr`).
- Arrays : `head`, `budget/<comp>`, `derived/…`, `mesh/`, `forcing/`, `lake_abacus/<id>`, `time` (CF),
  `crs`. Slabbing 256 MiB (`solver/modflow_common/field_slab.py:slab_steps`), BLOSC_ZSTD, shard >100 MiB.
- **LAK/SFR scalaires = Parquet, pas Zarr** ; seul l'abacus lac va en Zarr.

### 4.3 Parquet / CSV (tabulaire)

- `<basename>.parquet/{timeseries,budgets,mass_balance,metrics,provenance}.parquet`, exposés au RESULTS
  db via `read_parquet` views (`results/catalog/parquet_views.py`).
- LAK/SFR/catchment discharge → `timeseries.parquet` (`writes_parquet.py:write_timeseries*`).
- metrics/provenance = table DuckDB + miroir Parquet. Objectif scientifique + itérations calib = DuckDB
  seul.
- CSV = export à la demande (`results/exporters/csv.py` `COPY … TO … FORMAT CSV`).

### 4.4 Sidecars JSON

- Input provenance : `foo.tif.json` (`data/sidecars.py`, `cache_store.py:register`).
- MF6 obs (car flopy ne round-trip pas les boundname obs) : `<model>.lak.meta.json` (`LakeObsSpec`),
  `.sfr.meta.json` (`SfrObsSpec`), `.lake_abacus.json` — écrits par les builders
  (`build.py:_write_lake_obs_meta` / `_write_sfr_obs_meta` / `_write_lake_abacus_meta`), lus par les
  extractors.

### 4.5 Ponts cross-DB (ATTACH read-only, jamais fusionnés)

`results/catalog/cross_db.py` : RESULTS→DATA (`tracked_files.sha256` = `entries.sha256`),
GLOBAL INDEX→RESULTS (`GlobalIndex.refresh_federation` ATTACHe chaque catalog r/o). La clé de jointure
est `sha256` partout.

### 4.6 Lock de reproductibilité (`hydromodpy.lock`)

Manifeste **TOML** (pas un mutex), `data/data_freeze.py:write_lockfile` : versions
hydromodpy/python/git, binaires sha256 + `--version`, schema versions + `config_sha256`, inputs sha256.
Écrit post-run best-effort (`cli/commands/run.py:_post_run_lockfile_write`), lu par `--frozen`.
Verrous OS séparés (`filelock`) : `<db>.lock` (migration), `<zarr>/.lock` (écriture).

### 4.7 Calibration parallèle & la BD

Les trials légers écrivent **RIEN** (store/sim_id non posés, `lightweight=True`). Les lignes
`calibration_iterations` sont écrites **en série par le main thread** via la connexion partagée
(`persistence.append_iteration`). Seule la **promotion** du best rejoue le pipeline complet et écrit
durablement (register_simulation + Zarr + Parquet + DuckDB).

---

## 5. Post-processing & extraction

Entrée : `simulation/extraction/post_run.py:post_run_results` → `extract_run_outputs` →
`derive_run_outputs` → `auto_export_results` → `cleanup_solver_outputs`. Extractor MF6 =
`solver/modflow6/extractors/flow.py:Modflow6OutputAdapter`.

- **Time axis** : `_write_time_coordinate` lit TDIS `TIME_UNITS` + `START_DATE_TIME` → axe CF `/time`
  unique, réutilisé partout (`results/zarr_store/simulation_zarr.py:read_time`,
  `results/time_alignment.py:solver_time_index`).
- **Heads** : `.hds` slabé → `write_field_stack("head")` (Zarr).
- **Budget** : `.cbc` via `extractors/cbc_reader.py:Mf6CellBudgetReader` (single-pass) ; scalaires →
  flux_in/out /spt → `write_budgets` (Parquet) ; champs spatiaux (si activés) slabés → Zarr `budget/`.
- **Mass balance** : parse `.lst` (`_extract_mass_balance`) → `write_mass_balances`.
- **LAK** (`extractors/lake.py`) : obs CSV via sidecar ; states natifs, rates /spt → m³/s ;
  `ext_outflow`/`to_mvr` négativés (outflow positif) ; multi-outlet sommés ; `gwf_exchange` reconstruit
  = somme des obs `lak_connection` négativée ; fuite sous-barrage (`under_dam`) à part →
  `write_timeseries_batch` (Parquet).
- **SFR** (`extractors/sfr.py`) : obs CSV via sidecar ; sortie colonnaire (millions de points) →
  `write_timeseries_columns` (Parquet).
- **Catchment discharge** (`simulation/extraction/derivation/catchment_aggregation.py`) : si réseau,
  `discharge = SUM(ext_outflow)` SFR/LAK (requête DuckDB), DRN buffer **exclu** ; sinon fallback =
  |DRN| + runoff. Axe temporel = CF `/time` (fallback `date_range` seulement si absent).
- **Objectifs calibration** : lus **directement** des fichiers scratch (`calibration_extractors.py`,
  pas Zarr/Parquet) : discharge via `.cbc` (`extract_discharge_from_cbc`, **refuse si DRN-TO-MVR**),
  head via `.hds`, lake_level via l'obs LAK. Score NSE/KGE/RMSE/MAE
  (`calibration/objective.py:METRICS`, **pas de R²**), `align_observed_simulated`. Chemin composite via
  `CompositeObjective`.

---

## 6. Pièges & subtilités

- **Box-buffer ≠ watershed** : top modèle = DEM box-buffer, `inactive_mask` ← nodata seul ;
  `domain_extent="watershed"` ne clippe pas l'idomain par défaut.
- **Deux axes temps** : froid (extraction/agrégation) = CF `/time` ; chaud (objectifs calib) =
  `boundaries[1:]` (fin de stress period). Horloges différentes.
- **Deux traitements DRN** : post-process (champ DRN, exclusion buffer) vs calibration (`.cbc`, refuse
  si MVR route le drainage).
- **Skew moteur** : API=libmf6, subprocess+steady-init=exe ; `warn_on_mf6_version_mismatch` alerte une
  fois.
- **Voronoi ≠ triangulation** : `GmshPlanarMesh2D` refuse le ragged POLYGON ; le dual ne vit qu'en
  `HydroMesh`/`PolygonFieldMesh` après le seam de dualisation.
- **Trials = zéro écriture BD** : seul le best promu écrit durablement.
- **Pas de D-infinity** : routage D8 uniquement.
