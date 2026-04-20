# Rapport de conformité architecture — HydroModPy v0.4

**Date :** 2026-04-21
**Branche :** `dev-refact_v2` au commit `31b90697` (HEAD, avant F08)
**Base :** `run_migration.sh` (P01-P13) + `run_finalization.sh` (F01-F07), phase F08 en cours
**Méthodologie :** vérification directe du code, indépendante de `migration_report_dev_refact_v2.md` (obsolète).
**Fichier de référence pour chaque spec :** `architecture_cible/XX_*.md`.

Ce rapport atteste la conformité du codebase v0.4 aux 14 spécifications
d'architecture cible, en inventoriant pour chaque spec un ensemble de
_checkpoints_ concrets (fichier/classe/CLI/table DuckDB/import). Chaque
checkpoint est noté :

- **OK**       — conforme, avec une preuve (file:line ou commande).
- **ÉCART**    — divergence assumée/documentée ailleurs (F02, OVERRIDE spec, etc.).
- **MANQUANT** — divergence résiduelle. Une tâche de suivi est proposée.

---

## Executive summary

| Spec | OK | Écart | Manquant | Verdict global |
|------|----|-------|----------|----------------|
| 01_structure_packages.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 02_config_pydantic.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 03_data_contracts.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 04_storage_ideal.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 05_solver_contracts.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 06_pipeline_execution.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 07_calibration.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 08_postprocess_display.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 09_tests_ideaux.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10_ux_cli_api.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 11_frontend_ready.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 12_input_data_rethink.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 13_coherence_globale.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 14_plan_migration.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| **TOTAL** | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## Détail par spécification

### 01_structure_packages.md
**Résumé :** L'arborescence actuelle diverge fortement de la cible (pas de `_cli/`, pas de `physics/`, pas de `core/io|logging|exceptions`, `watershed/` toujours présent, packages `pipeline/` et `schema/` non prévus, profondeur 6, god-modules > 2000 l. toujours présents).
**Checkpoints :** 25 au total, OK=5, ÉCART=17, MANQUANT=3.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | Package `_cli/` remplace `__main__.py` monolithique | ÉCART | `hydromodpy/_cli` n'existe pas ; `hydromodpy/__main__.py` = 1890 lignes (cible ≤ 80). |
| 2 | `__init__.py` ≤ 80 lignes, sans bootstrap PROJ_DATA ni `LogManager()` eager | ÉCART | `hydromodpy/__init__.py` = 448 lignes ; lignes 20–218 = bootstrap PROJ_DATA, ligne 243 `_log_manager = LogManager(...)` au chargement. |
| 3 | `core/` est feuille du DAG (aucune dépendance `hydromodpy.*`) | ÉCART | `rg '^from hydromodpy\.(?!core)' hydromodpy/core` → 53 occurrences dans 9 fichiers (`core/config/hydromodpy_config.py:13`, `core/state/setup.py:8`, `core/state/data.py:3`, `core/config/generate_toml.py:11`…). |
| 4 | `core/exceptions.py` + hiérarchie centrale utilisée | ÉCART | Aucun `core/exceptions.py` ni `hydromodpy/exceptions.py`. Les `*Error` trouvés sont dispersés dans `data/adapters/*`. |
| 5 | `core/io/` (raster_io, vector_io, crs, http_client) | MANQUANT | `hydromodpy/core/io` absent. Utilitaires éparpillés dans `core/tools/` (`raster_io.py`, `geospatial.py`, `io_utils.py`). |
| 6 | `core/logging/` | MANQUANT | Absent. `LogManager` dans `core/tools/log_manager.py`. |
| 7 | `core/version.py` avec `__version__` isolé | ÉCART | Calculé inline dans `hydromodpy/__init__.py:229-236`. |
| 8 | `core/backends/` supprimé, backends déplacés sous `spatial/delineation/` | OK | `core/backends` absent ; `spatial/delineation/` contient `base.py`, `registry.py`, `whitebox_cli_backend.py`, `whitebox_workflows_backend.py`, `pysheds_backend.py`, `synthetic_backend.py`. |
| 9 | Package `process/` renommé en `physics/` | ÉCART | `hydromodpy/physics` absent ; `hydromodpy/process/` conservé (décision de scope). |
| 10 | Package `watershed/` supprimé | ÉCART | `hydromodpy/watershed/` toujours présent (façade legacy). |
| 11 | `workflow/` absorbé dans `simulation/workflows/` | ÉCART | `workflow/` top-level inchangé ; `simulation/workflows/` n'existe pas. |
| 12 | `runners/` top-level disparaît | ÉCART | `hydromodpy/runners/` toujours présent (shells CLI). |
| 13 | `simulation/results/` renommé en `simulation/extraction/` | ÉCART | Toujours `simulation/results/` (collision avec `results/` non levée). |
| 14 | `solver/utils/mesh/` déplacé vers `spatial/mesh/` | ÉCART | `solver/utils/mesh/` conservé (cartesian_grid + gmsh_grid). |
| 15 | `data/common/` aplati (`data/base_manager.py`) | ÉCART | `data/common/` conservé avec `base_manager.py`, `base_config.py`, `clients/`, etc. |
| 16 | Pas de duplication `data/{hydrometry,…}/` vs `data/variables/…/` | ÉCART | Les deux coexistent (façades legacy + managers canoniques). |
| 17 | Aucun `cases/` dans le runtime | ÉCART | 11 dossiers `cases/` dans le runtime (`data/variables/*/cases/`, `spatial/{field,domain,geographic}/cases/`, etc.). |
| 18 | Profondeur max d'import ≤ 4 niveaux | ÉCART | `solver/utils/mesh/gmsh_grid/cases/reference_3d_mesh/` = 6 niveaux. |
| 19 | Aucun fichier > 800 lignes | ÉCART | `solver/modflow6/modflow6.py` 2892, `analysis/comparison/runtime.py` 2061, `__main__.py` 1890, `analysis/batch/runtime.py` 1828, `solver/boussinesq/boussinesq.py` 1667, `solver/modflow_nwt/modflow/flow_to_modflow_adapter.py` 1394, `results/catalog.py` 1077. |
| 20 | `results/io/exporters/` dédié | ÉCART | `results/exporters/` à plat (csv/geotiff/hmp_package/netcdf/shapefile/vtu). Pas de `geopackage.py` ni `waterml.py`. |
| 21 | API publique `hmp.*` ≤ 25 symboles sans `*Manager/*Config/*Result` | ÉCART | `__init__.py` expose ~38 symboles dont `HydrographyConfig/Manager/Result`, `IntermittencyConfig/Manager`, `OceanicConfig/Manager`. |
| 22 | CLI `hmp`/`hydromodpy` installé via pyproject.toml | OK | Entries pointent sur `hydromodpy.__main__:main` (divergence chemin documentée : spec visait `_cli/main.py`). |
| 23 | `spatial/delineation/` multi-backend | OK | `base.py` (Protocol), `registry.py`, 4 backends (cli, workflows, pysheds, synthetic). |
| 24 | `spatial/surface.py` consolidé | OK (partiel) | `spatial/surface.py` existe mais `surface_sampling.py` subsiste à côté. |
| 25 | `validation_cases/` à la racine du repo | OK | `validation_cases/` présent mais coexiste avec les `cases/` in-package (cf. #17). |

**Écarts assumés :**
- CLI monolithique (`__main__.py`) conservée au lieu de `_cli/`.
- Sous-packages `pipeline/`, `schema/`, `calibration/`, `display/` top-level (non prévus par la spec qui les range sous `analysis/`).
- `analysis/calibration/`, `analysis/display/`, `analysis/postprocess/`, `analysis/metrics/` absents (fonctionnalités déplacées dans top-level dédiés).
- `process/` conservé au lieu de `physics/` (renommage hors scope migration).
- God-modules > 800 lignes : 7 fichiers dépassent la limite (décision post-v0.4).

**Manquants :**
- `core/io/` (raster_io.py, vector_io.py, crs.py, http_client.py) — suivi `v0.5-core-io-scaffold`.
- `core/logging/` dédié — suivi `v0.5-core-logging-extract`.
- `core/exceptions.py` hiérarchie centrale — suivi `v0.5-exceptions-hierarchy`.

---

### 02_config_pydantic.md
**Résumé :** Fondations Pydantic v2 + `ParamLevel` + types pint en place ; `HydroModelBase`, refonte `FlowConfig`/`Forcing`/`GridConfig`, round-trip `tomlkit` et validation physique centrale restent non implémentés.
**Checkpoints :** 21 au total, OK=8, ÉCART=9, MANQUANT=4.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `HydroModelBase` racine avec `ConfigDict(extra="forbid", serialize_by_alias, populate_by_name, validate_assignment)` | MANQUANT | `grep -r "class HydroModelBase"` → 0 résultat ; chaque config déclare son propre `model_config`. |
| 2 | `HydroModPyConfig` agrégateur root | OK (partiel) | `hydromodpy/core/config/hydromodpy_config.py:63` présent, mais `model_config = ConfigDict(arbitrary_types_allowed=True)` sans `extra="forbid"` (ÉCART). |
| 3 | `extra="forbid"` sur les sous-configs | OK | 116 occurrences dans 52 fichiers. |
| 4 | `from_toml` minimaliste | ÉCART | `hydromodpy_config.py:192-299` ~110 lignes avec dispatcher custom + `from_toml_section` (flow, data). |
| 5 | `to_toml(profile=...)` round-trip | MANQUANT | Aucun résultat sous `hydromodpy/core/config` ; seul `streamlit_config.py` en possède un équivalent ad-hoc. |
| 6 | Validateur cross-section (`solver.engine ↔ packages.engine`, `flow_regime=transient ⇒ ic`) | MANQUANT | Aucun `model_validator` transverse dans `HydroModPyConfig`. |
| 7 | `ParamLevel` user/dev/expert disponibles | OK | `hydromodpy/core/config/param_level.py:22` `PROFILES = {"user": 0, "dev": 1, "expert": 2}`. |
| 8 | `Profile(IntEnum)` comparable | ÉCART | `PROFILES` reste un `dict[str,int]` ; `ParamLevel` est dataclass. |
| 9 | `VisibleWhen` + validateur cible | ÉCART | `VisibleWhen` présent (`param_level.py:35`) mais aucun `_check_visible_when_targets`. |
| 10 | Types pint `Length`, `Time`, `FlowRate`, `HydraulicConductivity`, `SpecificStorage`, `SpecificYield`, `Area`, `Volume`, `Dimensionless` | OK | `core/units/types.py:161-171` ; ré-exports via `core/units/__init__.py:14-24`. |
| 11 | Registre pint partagé `UREG` | OK | `core/units/registry.py` + `UREG` exporté `core/units/__init__.py:13`. |
| 12 | `pydantic-pint` en dépendance core | OK | `pyproject.toml:58-59`. |
| 13 | `FlowPhysicalProperties` migré vers types pint (F01) | OK | `process/flow/physical_properties.py:39-41,59,75,88` utilise `HydraulicConductivity/SpecificYield/SpecificStorage`. |
| 14 | xfail `test_bare_number_falls_back_to_canonical_unit` + `test_flow_physical_properties_defaults_and_overrides` résolus (F01) | OK | `tests/unit/config/test_units_roundtrip.py:34,93` plus aucun marker `xfail`. |
| 15 | `FlowConfig` refactoré (runtime: FlowRuntimeConfig, types pint) | ÉCART | `process/flow/flow_config.py:51` hérite encore de `ProcessSpatialConfig` ; pas d'import pint (confirme F01 scope limité). |
| 16 | `TimeseriesVariableConfig` factorisant etp/humidity/... | MANQUANT | Les 14 configs timeseries restent séparées. |
| 17 | Union discriminée `Forcing` | MANQUANT | `ConstantForcing/SyntheticForcing/CsvForcing` absents. |
| 18 | `GridConfig` unifié + suppression suffixe `Schema` | ÉCART | `SGridConfig` toujours présent ; 31 classes `*Schema` subsistent. |
| 19 | CLI `hmp config <out.toml> --profile {user,dev,expert}` | OK | `__main__.py:1470-1475` + `_cmd_config`. |
| 20 | CLI `hmp schema export` + `hmp config schema` | OK | `__main__.py:1491-1509` + `1517-1533`. |
| 21 | `PHYSICAL_BOUNDS` centralisé + `validate_physical_value` | ÉCART | Seul `calibration/parameters.py` utilise des bounds physiques ad-hoc ; pas de `spatial/field/core/physical_bounds.py`. |

**Écarts assumés :**
- `HydroModPyConfig` conserve un `from_toml` impératif avec dispatcher — post-v0.4.
- `FlowConfig` hérite toujours de `ProcessSpatialConfig` et n'a pas migré vers pint (dette F01 tracée).
- Suffixe `Schema` encore porté par 31 classes dans 6 fichiers.
- `Profile(IntEnum)` non introduit : `PROFILES` dict suffit à l'implémentation courante.

**Manquants :**
- `hydromodpy/core/config/base.py::HydroModelBase` (suivi `v0.5-config-hydromodelbase`).
- `to_toml(profile=...)` via `tomlkit` (suivi `v0.5-toml-roundtrip`).
- `TimeseriesVariableConfig` factorisation (suivi `v0.5-timeseries-refactor`).
- `Forcing` discriminated union + `PHYSICAL_BOUNDS` central (suivi `v0.5-forcing-union` et `v0.5-physical-bounds`).

---

### 03_data_contracts.md
**Résumé :** La couche `data/` couvre les contrats de base (LoadResult, PointRecord, FieldRecord), la planification d'inférence (warn/strict), le scaffold, l'auto_scan, les trois adaptateurs utilisateur et le CLI `hmp data`, mais la refonte « contrats typés » (schemas pandera, DataSource Protocol, cache 6 tables) n'a pas encore été appliquée.
**Checkpoints :** 22 au total, OK=13, ÉCART=6, MANQUANT=2, N/A=1.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `BaseVariableManager` ABC avec `load()` + `_fetch_from_source` abstrait | OK | `hydromodpy/data/common/base_manager.py:44`, `load()` L67, `_fetch_from_source` `@abstractmethod` L102 (491 L). |
| 2 | `LoadResult` contract (points + fields + warnings) | OK | `hydromodpy/data/contracts/load_result.py:12`. |
| 3 | `PointRecord` avec `data: pd.DataFrame`, `date_start/end`, `location` | OK | `hydromodpy/data/contracts/timeseries.py:19` (spec vise frozen + pd.Series : divergence mineure). |
| 4 | `FieldRecord` contrat moderne (Dataset obligatoire) | ÉCART | `data/contracts/spatial_field.py:17` utilise `Union["xr.Dataset", Path]`. |
| 5 | `DataManagersPlanner` résout plan explicite + inféré | OK | `hydromodpy/data/planner.py:19` (157 L). |
| 6 | Règles d'inférence (geology via zone_ids, stream/ocean via active_bc) | OK | `planner.py:5-7` + logique L64-110. |
| 7 | `data.inference_mode` literal `warn\|strict` | OK | `data/data_managers_config.py:85-90`, validator L197-207. |
| 8 | `DataCatalogDuckDB` avec API cache | OK | `data/registry/catalog_duckdb.py:85` + context manager. |
| 9 | Scaffold `hmp init` (dossiers custom + readmes) | OK | `data/scaffold.py:1-49` + `_cmd_init` (`__main__.py:409`). |
| 10 | `auto_scan` pour `{variable}_custom/` | OK | `data/auto_scan.py:1-70`, `scan_custom`/`check_custom` utilisés `__main__.py:93,1139`. |
| 11 | Client SIM2 Météo-France (F07 rename) | OK | `data/common/clients/sim2_meteofrance.py` présent, ancien `sim2_inrae.py` absent. |
| 12 | Adapter CSV → Parquet | OK | `data/adapters/csv_to_parquet.py:1-12`. |
| 13 | Adapter SHP → GeoParquet | OK | `data/adapters/shp_to_geoparquet.py:19-27`. |
| 14 | Adapter ASC → GeoTIFF (COG) | OK | `data/adapters/asc_to_geotiff.py:22-40`. |
| 15 | CLI `hmp data {check,list,add}` | OK | `__main__.py:1122-1232` dispatch + `1756-1788` argparse. |
| 16 | Invalidation cache par mtime (OVERRIDE spec 12 vs SHA-256 §5.4) | OK | `auto_scan.py:78-101` `_last_indexed_mtime` ; `catalog_duckdb.py:41` `file_mtime DOUBLE`. Aucun SHA-256 (conforme OVERRIDE). |
| 17 | Schémas pandera `data/schemas/` | MANQUANT | Pas de `hydromodpy/data/schemas/` ; `pandera` non présent dans `hydromodpy/data`. |
| 18 | `DataContractViolation` exception | MANQUANT | 0 résultat ; seule `TimeSeriesValidationError` existe. |
| 19 | Cache à 6 tables (`artifacts`, `provenance`, `stations`, `coverage`, `failures`, `validation_reports`) | ÉCART | `catalog_duckdb.py` 2 tables (`entries` + `api_coverage`). |
| 20 | Protocol `DataSource` + `@register_source` | ÉCART | ABC `BaseVariableManager` conservé ; `apis → sources` non effectué. |
| 21 | `runtime_loader.py` remplacé par `loader.py` pur | ÉCART | `data/runtime_loader.py` toujours présent (891 L). |
| 22 | `base_field_manager.py` supprimé | ÉCART | Toujours présent (386 L). |

**Écarts assumés :**
- La feuille de route §7 (refonte DataSource Protocol / schemas pandera / cache 6 tables) n'est pas démarrée ; le code reste conforme à l'architecture pré-refactor (cohérent avec CLAUDE.md).
- `FieldRecord` tolère encore `Union[Dataset, Path]`.
- Checkpoint #16 : OVERRIDE utilisateur (mtime) prévaut sur la règle §0.10 / §5.4 du spec.

**Manquants :**
- `data/schemas/` et contrats pandera (suivi `v0.5-data-schemas`).
- Exception `DataContractViolation` (suivi `v0.5-data-exceptions`).

---

### 04_storage_ideal.md
**Résumé :** Le schéma DuckDB à 12 tables, le layout Zarr et les classes `SimulationCatalog/SimulationZarr/Simulation/SimulationGroup` sont présents et alignés avec la décision clean-slate, mais plusieurs éléments riches du design (`runs_environment`/`stations`/`tags`/`observations`, ENUMs/FK CASCADE/RTREE, CF-UGRID, chunking balanced, manifest `tar.zst`) restent non implémentés.
**Checkpoints :** 25 au total, OK=14, ÉCART=7, MANQUANT=4.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | 12 tables DuckDB exactes | OK | `catalog_schema.py:307-320` `TABLE_NAMES` liste précisément ces 12 tables. |
| 2 | Absence de `_schema_version` (clean slate P02) | OK | Aucun match dans `hydromodpy/results/` ; docstring `catalog_schema.py:9-13` confirme. |
| 3 | Colonne `config_snapshot JSON` dans `simulations` | OK | `catalog_schema.py:75`. |
| 4 | Colonne `geographic_fingerprint VARCHAR` + index | OK | `catalog_schema.py:81` + index `ix_sim_geo_fp` L100. |
| 5 | PK `simulations(sim_id UUID)` + 29 colonnes clés | OK | `catalog_schema.py:46-93`. |
| 6 | Table `parameters` PK (sim_id, param_name, zone_id) + DEFAULT `_homogeneous` | OK | `catalog_schema.py:107-116` (default `_homogeneous` au lieu de `__global__` du spec §2.2 L357). |
| 7 | Table `timeseries` PK (sim_id, station_id, variable, datetime) TIMESTAMPTZ | OK | `catalog_schema.py:136-145`. |
| 8 | Table `budgets` PK (sim_id, timestep, zone_id, component) | OK | `catalog_schema.py:153-166`. |
| 9 | Table `metrics` PK inclut `variable` | OK | `catalog_schema.py:130`. |
| 10 | Table `mass_balance` PK (sim_id, timestep) + total_in/out/storage/percent_error | OK | `catalog_schema.py:171-182`. |
| 11 | Table `observation_points` PK (sim_id, station_id) + (x, y, cell_id, layer) | OK | `catalog_schema.py:189-198`. |
| 12 | Table `provenance` PK (sim_id, variable, source_ref) + source_sha256 + payload_sha256 + stats JSON | OK | `catalog_schema.py:203-222`. |
| 13 | Tables `calibration_sessions` + `calibration_iterations` | OK | `catalog_schema.py:229-269` avec `best_sim_id`, `from_cache`, `params_hash`. |
| 14 | Tables `geographic_features` + `geographic_metadata` | OK | `catalog_schema.py:276-300`. |
| 15 | Compression Zarr BLOSC-ZSTD clevel=3 | OK | `zarr_store.py:14`. |
| 16 | Layout `simulations/<uuid>.zarr/` | OK | `catalog.py:183` + `catalog.py:100-101`. |
| 17 | Classes canoniques `SimulationCatalog/SimulationZarr/Simulation/SimulationGroup` | OK | `catalog.py:90`, `zarr_store.py:19`, `simulation.py:19`, `simulation_group.py:14`. |
| 18 | Méthodes catalog (`register_simulation`, `write_*`, `finalize`, `best`, `find`, `latest`, `sql`, `export_package`, `import_package`) | OK | F05 rename vérifié `catalog.py:845` (`export_package`) et L893 (`import_package`). |
| 19 | Chunking Zarr `(1, n_layers, n_cells)` | ÉCART | `zarr_store.py:169-173` implémente le chunking (1, L, N) ; spec cible `balanced`, assumé comme phase initiale. |
| 20 | Sous-groupes Zarr (`mesh/`, `head/`, `derived/`, `budget/`, `pathlines/`, `geographic/`) | ÉCART | `zarr_store.py:16` crée en plus `forcing` (spec §9.2 marqué `[SUPPRIME]`) ; `geographic/` reste dans le Zarr même si `GeographicCache` existe. |
| 21 | Format portable `.hmp` tar.zst + manifest.json + SHA-256 | ÉCART | `exporters/hmp_package.py:17-21` indique "pragmatic form … will evolve into the full tar.zst" ; produit un **dossier** (non archive). |
| 22 | Métadonnées Zarr CF-1.11 + UGRID-1.0 + `consolidate_metadata` + `to_xarray` | MANQUANT | `zarr_store.py:107-148` écrit seulement `vertices`, `face_node_connectivity`, `z_interfaces`. Pas de `CF_REGISTRY`, pas de `write_time`, pas de scalar `crs`. |
| 23 | Tables additionnelles `runs_environment`, `tags`, `stations`, `observations` | MANQUANT | Non présentes ; §9.1 les marque `[NOUVEAU]`. |
| 24 | Vues `v_simulation_summary`, `v_best_per_project`, `v_params_wide`, `v_metrics_wide` | MANQUANT | Aucune `CREATE VIEW` dans `catalog_schema.py`. |
| 25 | `SimulationGroup.to_xarray(variable, dim="sim")` | MANQUANT | Seules `best/worst/top/to_dataframe/to_csv` existent. |

**Écarts assumés :**
- Chunking Zarr `(1, n_layers, n_cells)` toujours actif (décrit tel quel dans `CLAUDE.md`).
- Sous-groupe Zarr `forcing/` conservé ; `geographic/` dupliqué avec le cache content-addressable.
- Format `.hmp` reste un dossier pragmatique (non tar.zst, sans manifest canonique) — auto-admis.
- PK `parameters.zone_id DEFAULT '_homogeneous'` (au lieu de `__global__`) — cohérent avec les constantes internes.
- Absence de FK `ON DELETE CASCADE` / ENUMs SQL / RTREE : docstring `catalog_schema.py:14-20` l'assume (bug DuckDB #11132).

**Manquants :**
- 4 tables `[NOUVEAU]` (`runs_environment`, `tags`, `stations`, `observations`) — suivi `v0.5-duckdb-tables`.
- Vues dénormalisées (`v_simulation_summary` etc.) — suivi `v0.5-duckdb-views`.
- Couche CF-1.11 / UGRID-1.0 dans Zarr — suivi `v0.5-zarr-cf-ugrid`.
- `SimulationGroup.to_xarray(variable, dim="sim")` — suivi `v0.5-ensemble-xarray`.

---

### 05_solver_contracts.md
**Résumé :** Le protocole `SolverAdapter` à 5 méthodes et le registre `(process_type, solver_name)` sont en place côté `solver/base/`, les helpers MODFLOW communs sont complets et les tests de conformité existent, mais la fusion du double registre (`solver/base/` vs `simulation/adapters/`) et la taxonomie d'erreurs ne sont pas implémentées ; la duplication NWT/MF6 est assumée (F02).
**Checkpoints :** 14 au total, OK=10, ÉCART=3, MANQUANT=1.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `SolverAdapter` défini comme `@runtime_checkable Protocol` avec `process_type`/`solver_name` | OK | `solver/base/protocol.py:33-54`. |
| 2 | Les 5 méthodes `setup/build/run/extract/cleanup` déclarées | OK | `solver/base/protocol.py:40-53`. |
| 3 | `RunResult` `@dataclass(frozen=True)` avec `converged`, `output_dir`, `wall_time_s`, `iterations`, `residual`, `diagnostics` | OK | `solver/base/protocol.py:21-30` ; test gel `tests/unit/solver/test_solver_protocol.py:91-94`. |
| 4 | Registre `(process_type, solver_name) → adapter_cls` avec `register/get/unregister/list_pairs/pairs_for_process` + `replace` | OK | `solver/base/registry.py:18-82`. |
| 5 | `modflow_common/` = 5 fichiers (`flow_translator.py`, `boundary_packages.py`, `forcing_discretization.py`, `binary_reader.py`, `grid_mapping.py`) | OK | Tous présents + `__init__.py:1-105`. |
| 6 | Adapter NWT existe (~1391 l) | OK | `solver/modflow_nwt/modflow/flow_to_modflow_adapter.py` = 1394 lignes. |
| 7 | Adapter MF6 existe (~581 l) | OK | `solver/modflow6/flow_to_modflow_adapter.py` = 584 lignes. |
| 8 | En-têtes F02 pointant vers `nwt_sunset_plan.md` | OK | NWT `modflow_nwt/modflow/flow_to_modflow_adapter.py:2-4` et MF6 `modflow6/flow_to_modflow_adapter.py:1-3`. |
| 9 | Adapter Boussinesq présent avec contrat propre | OK | `solver/boussinesq/solver_contract.py` + `boussinesq.py`. |
| 10 | Aucune référence MODFLOW-2000 / mf2k / MODFLOW-USG | OK | `grep -i` : 0 occurrence de `modflow-2000`, `mf2k`, `mfusg`. |
| 11 | `test_solver_protocol.py` couvre conformité + ordre cycle de vie + gel `RunResult` | OK | `tests/unit/solver/test_solver_protocol.py:57-94` (6 tests). |
| 12 | `test_solver_registry.py` couvre `register/get/replace/list_pairs/pairs_for_process/is_adapter` | OK | `tests/unit/solver/test_solver_registry.py:37-87` (8 tests). |
| 13 | Pas de duplication NWT/MF6 dans `flow_to_modflow_adapter.py` | ÉCART | Décision F02 (`nwt_sunset_plan.md`) : NWT (1394 l) + MF6 (584 l) gardés séparés jusqu'au retrait NWT post-intégration LAK MF6. |
| 14 | Registre unique (cible : fusion adapters/compatibility/extractors) | ÉCART | Deux registres : `solver/base/registry.py` (canonique 5-méthodes) et `simulation/adapters/registry.py:17-24` (`execute(ctx)` monolithique). |

**Écarts assumés :**
- Duplication NWT/MF6 — décision F02 (`docs/developers/nwt_sunset_plan.md`).
- Double couche `solver/base/SolverAdapter` vs `simulation/adapters/SolverAdapter` — fusion reportée post-v0.4.
- Pas de découverte plugin/entry-points `hydromodpy.solver` — trois solveurs embarqués suffisent.

**Manquants :**
- Hiérarchie d'exceptions typées (`SolverError`, `SolverDivergedError`, `SolverTimeoutError`, `SolverBinaryError`, `SolverMassBalanceError`, etc., §4.3 / §8.1) — suivi `v0.5-solver-exceptions`.

---

### 06_pipeline_execution.md
**Résumé :** Le pipeline est présent en 11 steps alignés sur §1.1 avec `Pipeline`/`Step`/`PipelineState` conformes, ledger DuckDB, checkpoint zstd et `DerivedRegistry` à 4 dérivations canoniques ; les écarts principaux tiennent à la forme (`PipelineState` payload non typé par step, protocole `Step` simplifié) mais non à la sémantique.
**Checkpoints :** 18 au total, OK=16, ÉCART=2, MANQUANT=0.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `hydromodpy/pipeline/pipeline.py` | OK | 122 lignes. |
| 2 | `hydromodpy/pipeline/step.py` | OK | `Step` protocol avec `name` + `run()`. |
| 3 | `hydromodpy/pipeline/state.py` | OK | Présent. |
| 4 | `hydromodpy/pipeline/checkpoint.py` | OK | 136 lignes. |
| 5 | `hydromodpy/pipeline/ledger.py` | OK | Présent. |
| 6 | `Pipeline` orchestrateur ≤ 200 l avec `run(state, resume_from=...)` | OK | 122 l, gère ledger + checkpoint. |
| 7 | `Step` Protocol `runtime_checkable` avec `name` + `run` | OK | `step.py:18-29`. |
| 8 | `PipelineState` frozen dataclass + `advance()` immuable | OK | `state.py:19`. |
| 9 | Checkpoint zstd + chemin `<ws>/.hmp/checkpoints/<run_id>/<idx:02d>_<name>.pkl.zst` | OK | `checkpoint.py:32,57-62,103-106`. |
| 10 | Ledger DuckDB `steps` avec PK (run_id, step_index) | OK | `ledger.py:52-66` persisté à `<ws>/.hmp/checkpoints/steps_ledger.duckdb`. |
| 11 | 11 steps effectives (`step_00_validate.py` … `step_10_export.py`) | OK | `standard_steps()` retourne 11 instances. |
| 12 | Alignement spec §1.1 (11 steps, fusion domain+plan et open_store+solver) | OK | Conforme après réalignement F03. |
| 13 | `DerivedRegistry` dans `pipeline/derived.py` | OK | `derived.py:303` + tri topologique + skip input manquant. |
| 14 | 4 dérivations canoniques (`watertable_elevation`, `watertable_depth`, `seepage_mask`, `fluxes_from_budget`) | OK | `derived.py:426-467`. |
| 15 | `step_09_derive.py` applique la registry via `registry.apply(sim_zarr)` | OK | `steps/step_09_derive.py:29-88`. |
| 16 | CLI `hmp run --resume RUN_ID` | OK | `__main__.py:1562-1575` + `runners/simulation.py:_run_resume`. |
| 17 | Tests `test_pipeline_basic`, `test_pipeline_checkpoint`, `test_pipeline_full`, `test_derived_registry` | OK | `tests/unit/` + `tests/regression/fast/`. |
| 18 | `Step` Protocol typé générique `TIn`/`TOut` + dataclass par step | ÉCART | `Step` est non-générique ; `PipelineState.data: Mapping[str, Any]` au lieu d'une hiérarchie frozen par step (ValidatedState/ResolvedState/...). |

**Écarts assumés :**
- Typage I/O unique (`PipelineState.data: Mapping[str, Any]`) au lieu d'une hiérarchie frozen typée par step (§1.3/§1.4). Contrat frozen + `advance()` respecté.
- `_execute_step` attrape `BaseException` au lieu d'une hiérarchie `PipelineError` typée ; CLI sans `--until/--from/--dry-run/--no-checkpoint` (§5.4) — focus sur `--resume` seulement.

**Manquants :** Aucun.

---

### 07_calibration.md
**Résumé :** Le sous-système calibration est conforme aux OVERRIDES du spec (Optuna principal, PEST++ exclu, TOML simplifié, cache `params_hash` SHA-256, modes `save_runs`), avec quelques écarts mineurs vs layout détaillé du document.
**Checkpoints :** 18 au total, OK=15, ÉCART=3, MANQUANT=0.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | Dépendance `optuna` dans `pyproject.toml` | OK | `pyproject.toml:67`. |
| 2 | Package `hydromodpy/calibration/` présent | OK | engine.py, optimizer.py, objective.py, parameters.py, cache.py, persistence.py, cli.py, config.py, adapters/. |
| 3 | Suppression `hydromodpy/analysis/calibration/` | OK | Absent. |
| 4 | `engine.py` avec CalibrationEngine ask/tell | OK | + `CalibrationSession` dataclass. |
| 5 | `objective.py` avec Protocol `Objective` runtime_checkable | OK | `objective.py:48-55`. |
| 6 | `optimizer.py` avec Protocol `Optimizer` + `ParamSuggestion`/`EvaluationResult` | OK | `optimizer.py:38-58`. |
| 7 | `parameters.py` (Calibrable, transforms identity/log/logit) | OK | Présent. |
| 8 | `cache.py` — cache `params_hash` SHA-256 | OK | `cache.py:39-42` `hashlib.sha256(canonical_json(...)).hexdigest()`. |
| 9 | `persistence.py` — écritures DuckDB (start/append/finalize/top_n) | OK | Présent. |
| 10 | 3 adapters optimizer (scipy/optuna/grid) + 4 décorateurs `@register_optimizer` | OK | `adapters/scipy_adapter.py`, `optuna_adapter.py`, `grid_adapter.py`. |
| 11 | Décorateur `@register_optimizer` | OK | `optimizer.py:63-70`. |
| 12 | Modes `save_runs` (none/best_n/all) | OK | `config.py:27`. |
| 13 | Colonne DuckDB `params_hash` + index `ix_cal_iter_hash` | OK | `results/catalog_schema.py:255,268-269`. |
| 14 | TOML `[calibration]` + `[calibration.parameters]` (bounds/transform/prior) | OK | `config.py` `CalibrationConfig`, `CalibParameterDecl`. |
| 15 | CLI `hmp calibrate` | OK | `__main__.py:1837-1861`. |
| 16 | Retrait de PEST++/pyemu | OK | 0 import dans `hydromodpy/`. |
| 17 | Layout détaillé spec §2 (sous-packages `contracts/`, `optimizers/`, `objectives/`, `sensitivity/`, evaluator.py, batch.py) | ÉCART | Implémentation compacte mono-fichier, cohérente avec les OVERRIDES P09-P13. |
| 18 | `Evaluator` Protocol runtime_checkable + `SimulationEvaluator` dédié | ÉCART | L'engine prend simplement `EvaluatorFn = Callable[[ParamSuggestion], EvaluationResult]` (cli.py closure). |

**Écarts assumés :**
- Layout plat vs sous-packages détaillés du §2 — OVERRIDES simplifient le scope.
- `Evaluator` réduit à une `Callable` — design plus simple.
- `ObjectiveValue.is_scalar` omis — `vector is not None` remplit le même rôle.

**Manquants :** Aucun.

---

### 08_postprocess_display.md
**Résumé :** Le module `display/` est conforme sur le contrat Figure, le registre, les 9 figures canoniques, le helper UGRID, les métriques, les dérivés et la purge des env vars ; la cible d'architecture étendue (Thème, colormaps banlist, GeoFigureMixin, duration_curve/Piper/etc.) reste volontairement non implémentée pour v0.4.
**Checkpoints :** 19 au total, OK=14, ÉCART=2, MANQUANT=3.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `display/figure.py` : Figure Protocol + BaseFigure ABC | OK | `display/figure.py:55-76`. |
| 2 | `display/catalog.py` : register/get/list_figures/names | OK | `display/catalog.py:16-43`. |
| 3 | 9 figures canoniques sous `display/figures/` | OK | piezometric_map, hydrograph, cross_section, recharge_map, seepage_map, particle_tracks, concentration_map, water_budget, difference_map. |
| 4 | Chaque figure = `BaseFigure` + `@register` + `FigureSpec` | OK | 9 classes matchent ; test `tests/unit/test_figure_catalog.py:17-27`. |
| 5 | `display/_ugrid.py::render_face_field` unifie DIS + DISV | OK | `_ugrid.py:23-65` — `PolyCollection` sans `reshape(nrow,ncol)`. |
| 6 | `results/metrics.py` : 7 métriques (+ align) | OK | `metrics.py:18-27` `__all__ = ["align","bias","correlation","kge","log_nse","nse","pbias","rmse"]`. |
| 7 | Métriques robustes NaN + retournent `float` | OK | `align()` masque les non-finis. |
| 8 | `results/derived.py` : 4 fonctions canoniques | OK | `derived.py:22-27` `__all__ = ["fluxes_from_budget","seepage_mask","watertable_depth","watertable_elevation"]`. |
| 9 | `HYDROMODPY_NO_DISPLAY` purgé du package | OK | 0 occurrence dans `hydromodpy/`, `tests/`, `validation_cases/`. |
| 10 | `HYDROMODPY_NO_SAVE` purgé du package | OK | Idem. |
| 11 | `hydromodpy/analysis/display/` physiquement supprimé | OK | `analysis/` ne contient que `batch/`, `comparison/`, `capability_gallery.py`, `__init__.py`. |
| 12 | `hydromodpy/analysis/postprocess/` physiquement supprimé | OK | Idem. |
| 13 | `[display]` TOML section via `DisplayConfig` | OK | `display/config.py:17-45` (save, interactive, output_dir, dpi, figures) + intégré `core/config/hydromodpy_config.py:36,146,271`. |
| 14 | Tests contrat Figure (`test_figure_catalog.py`) | OK | 72 lignes, registration + protocol conformance. |
| 15 | Tests métriques + derived | OK | `test_metrics_nse.py`, `test_metrics_kge.py`, `test_derived_watertable.py`, `test_derived_registry.py`. |
| 16 | `DisplayConfig` expose `enabled/backend/preset/show/[display.overrides.*]` | ÉCART | Champs simplifiés (save/interactive/output_dir/dpi/figures) — intention respectée mais schéma cible plus riche (§9/§11). |
| 17 | Pipeline "derived écrits dans Zarr à l'extraction" | ÉCART | Fonctions pures `results/derived.py` présentes ; intégration systématique via extractors non vérifiable depuis ce module. |
| 18 | Infrastructures cibles (theme.py, colormaps.py banlist, renderer.py BackendManager, geo/, core/units/labels.py) | MANQUANT | Non implémentées — cible §3.3–§3.5/§8/§9. |
| 19 | Figures étendues (duration_curve, recession, Piper/Stiff/Schoeller, seasonal_boxplot, side_by_side, ensemble_band, calibration plots, watershed_id_card) | MANQUANT | `display/figures/` = 9 canoniques seulement. |

**Écarts assumés :**
- `DisplayConfig` minimal (save/interactive/output_dir/dpi/figures) — intention "CI-safe" respectée.
- Intégration derived → Zarr à confirmer côté extractors (hors périmètre display).

**Manquants :**
- Infrastructures cibles (theme, colormaps banlist, renderer, geo, labels) — suivi `v0.5-display-theme-colormap`.
- Corpus figures étendu (20+ figures supplémentaires spec §6) — suivi `v0.5-figure-library`.
- Tests d'interdiction (`test_no_banned_cmap_in_display`, `test_no_matplotlib_side_effects`, `test_display_never_writes_to_zarr`) — suivi `v0.5-display-guardtests`.

---

### 09_tests_ideaux.md
**Résumé :** F06 a amorcé la migration (dossier `integration/`, fixtures `tmp_workspace`/`minimal_config`, CI trois jobs avec flags Codecov) mais la suite cible (`unit ~80` fichiers, `_helpers/`, `e2e/`, MMS/Theis/Hantush, `pytest.ini` dédié, `TOLERANCES.md`) reste majoritairement non implémentée.
**Checkpoints :** 20 au total, OK=8, ÉCART=5, MANQUANT=7.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | Quatre tiers unit/integration/validation/e2e | ÉCART | unit/integration/validation/regression ; `tests/e2e/` absent ; `regression/` persiste (spec §2.1 fusionne dans validation/e2e). |
| 2 | `tests/integration/` avec `__init__.py` + `conftest.py` | OK | `conftest.py` autouse `_integration_tier_marker`. |
| 3 | Fixtures `tmp_workspace` + `minimal_config` dans `tests/conftest.py` | OK | Lignes 61-97. |
| 4 | `tests/README.md` documente les tiers | OK | Sections « Tiers », « Markers », « Writing new tests ». |
| 5 | CI job unit avec Codecov flag `unit` | OK | `.github/workflows/coverage.yml:11-65`. |
| 6 | CI job integration avec Codecov flag `integration` | OK | Lignes 67-121. |
| 7 | CI job regression (fast+extensive) avec flag `regression` | OK | Lignes 123-179. |
| 8 | Markers declared (13 marqueurs dont integration, coverage, petsc, extensive) | OK | `pyproject.toml:141-155`. |
| 9 | Marker `boussinesq`/`network`/`binary`/`gpu` | ÉCART | Absents — on vit avec `nwt`/`mf6`/`petsc`. |
| 10 | `tests/pytest.ini` dédié (sortie de `pyproject.toml`) | MANQUANT | Config reste dans `pyproject.toml`. |
| 11 | Suite pytest collecte sans erreur | OK | integration=20, unit=1878, regression+validation=97 tests collectés. |
| 12 | Ratio cible 75/17/6/2 | ÉCART | 82/1.5/12.8/0 (unit/integration/validation/e2e) — très éloigné. |
| 13 | `tests/_helpers/` renommé | MANQUANT | Toujours `tests/support/`. |
| 14 | `tests/TOLERANCES.md` avec justifications | MANQUANT | Seuls `README.md` et `README_timing_distribution.md` présents. |
| 15 | Auto-tag par chemin + timeouts par layer | ÉCART | Gère `fast`/`extensive` pour regression seulement ; pas de timeout layer ni auto-tag global. |
| 16 | Hook anti-subprocess dans `tests/unit/conftest.py` | MANQUANT | Aucun `tests/unit/conftest.py`. |
| 17 | Benchmarks Theis / Hantush / Ogata-Banks | MANQUANT | Absents de `tests/validation/analytical/transient/`. |
| 18 | MMS (Laplacien 1D, diffusion transitoire) | MANQUANT | Pas de `tests/validation/mms/`. |
| 19 | Seeds déterministes autouse + BLAS single-thread | ÉCART | `conftest.py` ne configure que `HYDROMODPY_TEST_SCRATCH_ROOT`/`TMPDIR`. |
| 20 | Migration 3 cross-module tests F06 vers `integration/` | OK | `test_calibration_bridge.py`, `test_results_adapters.py`, `test_results_post_run.py` + `test_fixtures_smoke.py`. |

**Écarts assumés :**
- Ratios éloignés de 75/17/6/2 — dégraissage `tests/unit/` hors scope v0.4.
- Markers secondaires `boussinesq`/`network`/`binary`/`gpu` non ajoutés.
- `tests/regression/` persistant — fusion dans validation/e2e reportée.

**Manquants :**
- `tests/e2e/` complet — suivi `v0.5-tests-e2e`.
- `tests/_helpers/` (fixtures_mesh/catalog/config/data.py, strategies.py, signatures.py, assertions.py) — suivi `v0.5-tests-helpers`.
- `tests/TOLERANCES.md` — suivi `v0.5-tests-tolerances`.
- `tests/pytest.ini` dédié — suivi `v0.5-tests-pytest-ini`.
- `tests/unit/conftest.py` hook anti-subprocess — suivi `v0.5-tests-unit-guardrails`.
- Benchmarks analytiques Theis/Hantush/Ogata-Banks + MMS — suivi `v0.5-validation-analytical-mms`.
- Fixture autouse `_deterministic_seeds` + BLAS mono-thread — suivi `v0.5-tests-determinism`.

---

### 10_ux_cli_api.md
**Résumé :** API Python conforme sur l'essentiel (lazy imports PEP 562, `__all__`, fluent API, `_repr_html_`, exit codes, catalog best/find/latest/sql), mais CLI incomplète — plusieurs sous-commandes spec absentes (`doctor`, `inspect`, `best`, `worst`, `delete`, `completion`, `--version`) et `py.typed` manquant.
**Checkpoints :** 20 au total, OK=13, ÉCART=3, MANQUANT=4.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | Lazy imports via `__getattr__` (PEP 562) | OK | `__init__.py:260` `_LAZY_IMPORTS`, `:303` `__getattr__`. |
| 2 | `__all__` exhaustif top-level | OK | `__init__.py:362-420` — 40+ symboles. |
| 3 | `hmp.open()` renvoie `SimulationCatalog` | OK | `__init__.py:321-329`. |
| 4 | `hmp.doctor()` top-level | OK (API) | `__init__.py:423-447`. **Pas de sous-commande CLI `hmp doctor`.** |
| 5 | `hmp.compare()` | OK | `__init__.py:353-359`. |
| 6 | `Simulation` / `SimulationPlan` / `SimulationGroup` exposés | OK | `_LAZY_IMPORTS` lignes 292-299. |
| 7 | `catalog.best(project, metric)` | OK | `catalog.py:800`. |
| 8 | `catalog.find(**filters) → SimulationGroup` | OK | `catalog.py:722-785`. |
| 9 | `catalog.latest(project)` | OK | `catalog.py:787`. |
| 10 | `catalog.sql(query)` | OK | `catalog.py:818`. |
| 11 | `catalog.export_package` / `import_package` | ÉCART | Présents (`catalog.py:845,893`). Spec CLI §5.2.8 parle de `hmp export --format hmp` — noms symétriques F05 vs nom asymétrique spec. |
| 12 | `Simulation` expose `field/timeseries/budget/metrics/plot` | OK | `simulation.py:184,131,158,112,308`. |
| 13 | `_repr_html_` sur classes clés Jupyter | OK (partiel) | `Simulation`, `SimulationGroup`, `SimulationCatalog`. Manque sur `HydroMesh`, `Geographic`, `SimulationPlan`, façade `Simulation`. |
| 14 | `SimulationGroup.to_dataframe()` | OK (nom diffère) | `simulation_group.py:151`. Spec attend `to_frame()` + `pivot()`. |
| 15 | Exit codes standardisés | OK | `__main__.py:47-52` (EXIT_OK=0, EXIT_CONFIG=1, EXIT_RUN_FAILED=2, EXIT_NOT_FOUND=3, EXIT_USER_ABORT=4). Test `test_cli_exit_codes.py:32-36`. |
| 16 | Sous-commandes canoniques (init/new/config/run/display/list/export) | OK | `hmp --help` confirmé. |
| 17 | Sous-commandes additionnelles (show, compare, import, calibrate, schema, test, data) | OK | Argparse L1790-1861. |
| 18 | Sous-commandes spec manquantes : `doctor`, `inspect`, `best`, `worst`, `delete`, `completion`, `--version` | MANQUANT | Absentes comme sous-parsers. |
| 19 | Marker `py.typed` (PEP 561) | MANQUANT | Fichier absent. |
| 20 | Tests exit codes + CLI | OK (partiel) | `test_cli_exit_codes.py` valide 5 codes ; pas de `test_ux_acceptance.py`. |

**Écarts assumés :**
- `catalog.export_package`/`import_package` symétriques (F05) vs spec `export_package`/CLI asymétrique.
- `SimulationGroup.to_dataframe()` au lieu de `to_frame()`.
- Exit codes : 4 codes métier + SIGINT 130 vs 6 codes spec §5.4 (solver/data/config distincts).

**Manquants :**
- Sous-commandes CLI `doctor`, `inspect`, `best`, `worst`, `delete`, `completion`, `--version` — suivi `v0.5-cli-missing-subcommands`.
- `hmp config {check,template}` sous-parsers — suivi `v0.5-cli-config-subparsers`.
- Fichier `hydromodpy/py.typed` (PEP 561) — suivi `v0.5-py-typed`.
- `_repr_html_` sur `HydroMesh`, `Geographic`, `SimulationPlan`, façade programmatique `Simulation` — suivi `v0.5-repr-html-extra`.
- `tests/integration/test_ux_acceptance.py` — suivi `v0.5-tests-ux-acceptance`.

---

## Écarts globaux assumés (décisions architecture)

_À compiler après les 14 vérifications._

---

## Manquants résiduels (à traiter post-v0.4)

_À compiler après les 14 vérifications._

---

## Conclusion

_À renseigner après synthèse._


## Écarts globaux assumés (décisions architecture)

_À compiler après les 14 vérifications._

---

## Manquants résiduels (à traiter post-v0.4)

_À compiler après les 14 vérifications._

---

## Conclusion

_À renseigner après synthèse._
