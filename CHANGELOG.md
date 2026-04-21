# Changelog

All notable changes to this project will be documented in this file.

The format follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention
and this project adheres to [Semantic Versioning](https://semver.org/).

---

## About this file

This changelog lists every significant modification of the HydroModPy project,
from new features to fixes and internal updates.

Each release section includes the following standard categories:

- **Added** – for new features
- **Changed** – for updates in existing functionality
- **Deprecated** – for soon-to-be removed features
- **Removed** – for removed features or files
- **Fixed** – for any bug fixes
- **Security** – for security improvements

### How to update it

1. During development, document all notable changes under the **[Unreleased]** section.
2. When creating a new release (e.g., `v0.1.1`), move that content into a new section
   named `## [v0.1.1] - YYYY-MM-DD`.
3. Keep the `[Unreleased]` section empty to start recording changes for the next release.

---

## [Unreleased]

### Added
- CLI subcommands `hmp doctor`, `hmp inspect <sim_id>`,
  `hmp best <project> [--metric nse]`, `hmp worst <project> [--metric nse]`,
  `hmp delete <sim_id> [-y]`, and `hmp completion {bash,zsh,fish}` (phase G07).
- `hmp --version` / `hmp -V` prints the HydroModPy version, Python, OS and
  git commit on a single line.
- `hmp config check <file.toml>` validates a TOML against the Pydantic
  `HydroModPyConfig` model and exits with `EXIT_CONFIG=1` on failure.
- `hmp config template [output]` is now the explicit subcommand for
  template generation (alongside `hmp config schema` / `hmp config wizard`).
- `hmp run` accepts `--from STEP`, `--until STEP`, `--dry-run` and
  `--no-checkpoint` to drive the pipeline execution explicitly (spec
  `architecture_cible/06_pipeline_execution.md §5.4`). `--dry-run` prints
  the workflow plan and step list without executing.
- CLI integration tests `tests/integration/test_cli_subcommands.py` and UX
  acceptance test `tests/integration/test_ux_acceptance.py` cover every
  subcommand's `--help`, the `--version` flag, the `completion` output and
  the `init → new → config template → run --dry-run → list → doctor` flow.
- Four new DuckDB catalog tables (phase G05):
  - `runs_environment` — Python / HydroModPy version, platform, hostname,
    user, CPU info, memory, git commit and pip-freeze JSON for each run,
    keyed by `sim_id`.
  - `tags` — normalized `(sim_id, tag)` index with `added_at` / `added_by`
    columns (replaces the legacy `simulations.tags VARCHAR[]` array column
    for new writes).
  - `stations` — global station catalog `(station_id, variable_type)` with
    lat/lon, elevation, validity window, source and free-form JSON
    metadata.
  - `observations` — time-indexed observed values tied to the `stations`
    catalog (keyed by `station_id, variable_type, datetime`).
- Four denormalized views to simplify discovery queries:
  - `v_simulation_summary` — one row per simulation with outlet NSE / KGE /
    RMSE / R² pulled from the `metrics` table.
  - `v_best_per_project` — per-project best simulation by NSE.
  - `v_metrics_wide` — PIVOT of `metrics` over the known metric names
    (`nse`, `kge`, `rmse`, `r2`, `bias`, `pbias`, `mae`, `mse`).
  - `v_params_wide` — one row per simulation with a `MAP` of
    `param_name[::zone_id]` → value.
- `hydromodpy.results.field_registry` — canonical CF-1.11 registry
  exposing `FieldDescriptor` and 18 descriptors for every field produced
  or consumed by HydroModPy (`head`, `watertable_depth`, `seepage_mask`,
  `recharge`, `hydraulic_conductivity`, …). Figures, exports and the
  Zarr writer all resolve field metadata through this module.
- CF-1.11 / UGRID-1.0 metadata on every simulation Zarr store:
  `Conventions="CF-1.11 UGRID-1.0"` at the root, scalar
  `mesh/topology` variable (`cf_role="mesh_topology"`), CF `time` and
  scalar `crs` coordinate variables, and per-field
  `standard_name`, `long_name`, `units`, `cell_methods`, `coordinates`
  and `grid_mapping` attributes attached on first write.
- `SimulationZarr.to_xarray()` and `SimulationZarr.consolidate_metadata()`
  — produce a CF-aware `xarray.Dataset` (with registered fields, CF time
  and CRS coordinates) and persist a consolidated `zarr.json` for fast
  reopening.
- `SimulationGroup.to_xarray(variable, dim="sim")` — concatenate the
  same field across every simulation of the group, with `sim_id` as the
  stacking coordinate.
- Portable `.hmp` package format: a single `tar.zst` archive containing
  `manifest.json` (format version, sim_id, per-file SHA-256),
  `catalog_snapshot.duckdb` (one-simulation DuckDB dump),
  `simulation.zarr.zip`, an optional `geographic/` cache payload and a
  human-readable `README.md`. `SimulationCatalog.import_package` verifies
  every file's SHA-256 before any mutation.
- `SimulationZarr(path, balanced=True)` — opt-in balanced chunking that
  targets ~1 MiB chunks by packing multiple timesteps along the time
  axis (falls back to `(1, n_layers, n_cells)` for large steps).
- `zstandard>=0.22` added as a core dependency (required by the
  `tar.zst` `.hmp` exporter).
- `hydromodpy.core.exceptions` — canonical typed exception hierarchy
  (`HydroModPyError` base + `ConfigError`, `DataError`, `MeshError`,
  `SolverError`, `PipelineError`, `CalibrationError`, `DisplayError`,
  `StorageError` sub-trees). Each class carries a stable `HMPY.Exxx` code
  and optional `sim_id` / `run_id` context.
- `hydromodpy.core.io` subpackage — canonical I/O helpers
  (`raster_io`, `vector_io`, `crs`, `canonical_json`, `http_client` stub).
- `hydromodpy.core.logging` subpackage hosting `LogManager`, `get_logger`,
  and `setup_simulation_log` (moved from `core.tools.log_manager`).
- `hydromodpy.core.version` — single source for `__version__`.
- `hydromodpy.core.config.base.HydroModelBase` — shared Pydantic root that
  centralises the strictness defaults (`extra="forbid"`,
  `validate_assignment=True`, `serialize_by_alias=True`,
  `populate_by_name=True`, `str_strip_whitespace=True`,
  `ser_json_inf_nan="strings"`) and runs `VisibleWhen` metadata
  sanity checks. Every HydroModPy config class now inherits from it.
- `hydromodpy.core.config.toml_io.dump_toml_with_comments` and
  `HydroModelBase.to_toml(profile=...)` — :mod:`tomlkit`-powered
  round-trip helper that emits a TOML document filtered by the
  requested `user` / `dev` / `expert` profile.
- `hydromodpy.spatial.field.core.physical_bounds.PHYSICAL_BOUNDS` +
  `validate_physical_value` — central registry of acceptable physical
  ranges (K, Sy, Ss, porosity, transmissivity, recharge, elevation,
  solver tolerances, …) wired into section-level config validators.
- `hydromodpy.physics.base.forcing` — discriminated union
  (`ConstantForcing | CsvForcing | SyntheticForcing`) factoring the
  flow-boundary / sinks-sources forcing payloads behind a single `kind`
  discriminator.
- `hydromodpy.physics.flow.flow_config.FlowRuntimeConfig` — grouped
  view over the flow-runtime Boussinesq knobs (`backend`,
  `surface_model`, `max_iterations`, `tol_residual_inf`,
  `tol_state_update_inf`) accessible as `FlowConfig.runtime`.
- `hydromodpy.data.variables.timeseries_variable_config.TimeseriesVariableConfig`
  — shared CSV-grammar base (`col_id`, `col_x`, `col_y`, `col_crs`,
  `col_datetime`, `col_value`, `default_crs`, `station_ids`, `extent`,
  `force_refresh`, `mask_path`) factoring ~14 near-identical
  `[data.<variable>]` configs.
- `HydroModPyConfig` gained a cross-section `model_validator`
  enforcing: `data.inference_mode='strict'` ⇒ `data.types` non-empty;
  `[calibration]` present ⇒ `flow.param_list` non-empty; Boussinesq
  engine forbids `[transport]`.
- `tomlkit` promoted to a core dependency in `pyproject.toml` (required
  by the round-trip TOML writer).
- `hydromodpy.core.io.http_client.HTTPClient` — unified HTTP client
  used by every data source. Features: persistent `requests.Session`,
  exponential backoff with jitter, honours `Retry-After` (seconds or
  HTTP-date), configurable default timeout, per-host concurrency
  token bucket, `stream()` with SHA-256 streaming, `get_json()` with
  optional Pydantic validation, and pre/post request hooks.
- `hydromodpy.data.schemas` — pandera-backed contracts: `TimeSeriesSchema`,
  `StationCollectionSchema`, `LithologyTableSchema`, `CatchmentPolygonSchema`
  and `DEMContract`, each surfacing failures as
  `hydromodpy.core.exceptions.DataContractViolation` (HMPY.E201).
- `hydromodpy.data.registry.catalog_duckdb` — 6 additional tables
  (`artifacts`, `provenance`, `stations`, `coverage`, `failures`,
  `validation_reports`) bringing the InputCatalog to 7 tables total
  (spec 03 §5.2 / spec 12 §5). Write helpers:
  `write_artifact`, `write_provenance`, `upsert_station`,
  `write_coverage`, `write_failure`, `write_validation_report`, plus
  `check_and_fix` (drop missing, refresh mtimes) and
  `prune_older_than`.
- `hydromodpy.data.lockfile` — reproducible data lockfile
  (`hydromodpy.lock`): `write_lockfile`, `read_lockfile`,
  `verify_frozen`, `archive_lockfile`, `restore_archive` plus
  `set_frozen_mode` / `is_frozen_mode` for the new `--frozen`
  flag on `hmp run` and `hmp data add`.
- `hmp lock` CLI sub-commands: `update`, `archive`, `restore`,
  `verify`.
- `hmp data` CLI extensions: `remove`, `prune`, `export`, `import`
  plus the new `check --fix` mode.
- `hydromodpy.data.sources` — minimal `DataSource` Protocol with a
  `register_source` decorator / `get_source` / `list_sources` registry
  for pluggable data sources without the full manager boilerplate.
- `pandera` promoted to a core dependency in `pyproject.toml`
  (required by `hydromodpy.data.schemas`).
- Display infrastructure (phase G06):
  - `hydromodpy/display/theme.py` — three `Theme` presets (`default`,
    `print`, `dark`) and an :func:`apply_theme` helper that configures
    matplotlib `rcParams` (palette, grid, fonts, background).
  - `hydromodpy/display/colormaps.py` — perceptually-banned colormap set
    (`jet`, `rainbow`, `hsv`, `nipy_spectral`, `gist_rainbow`), a
    `get_cmap` gate and a `check_no_banned_in_call` helper used by the
    display unit-tests.
  - `hydromodpy/display/renderer.py` — `BackendManager` context manager
    and `save_figure` helper, switching matplotlib to Agg in headless
    mode and tearing down every open figure on exit.
  - `hydromodpy/display/geo/` — `GeoFigureMixin` (scale bar, north
    arrow, optional basemap) and an opt-in `basemaps` wrapper around
    `contextily`.
  - `hydromodpy/core/units/labels.py` — `AXIS_LABELS` and
    :func:`axis_label` so figures share one canonical terminology.
- `DisplayConfig` (`[display]` TOML section) enriched with `enabled`,
  `backend`, `preset`, `show`, `cmap`, and `overrides`. `interactive`
  was renamed to `show` (no compat alias).
- Eleven new registered figures in `hydromodpy/display/figures/`:
  `duration_curve`, `recession`, `piper_diagram`, `stiff_diagram`,
  `schoeller_diagram`, `seasonal_boxplot`, `side_by_side`,
  `ensemble_band`, `calibration_convergence`,
  `calibration_pairplot`, `watershed_id_card` — bringing the total to
  twenty registered figure names.
- `_repr_html_` added on `HydroMesh`, `CatchmentDelineation`,
  `SimulationPlan` and the `Simulation` façade (`hydromodpy.project`).
- Three display unit-tests enforcing the corpus invariants: no banned
  colormap literals, no matplotlib side-effects at import time, no
  write calls from figure code.

### Changed
- **BREAKING**: project version bumped to `0.5.0.dev0`.
- **BREAKING** (G07): CLI implementation relocated from
  `hydromodpy/__main__.py` (1900+ lines) to the `hydromodpy/_cli/`
  package (one subcommand per file). Entry points `hmp` and
  `hydromodpy` now resolve `hydromodpy._cli:main`.
  `hydromodpy/__main__.py` is reduced to a 12-line shim that forwards
  to `_cli.main` so `python -m hydromodpy` keeps working.
- **BREAKING** (G07): bare form `hmp config FILE.toml` removed — use
  `hmp config template FILE.toml` (new explicit subcommand). Other
  legacy aliases (`hmp config schema`, `hmp config wizard`) are kept.
- **BREAKING** (G07): `hydromodpy/runners/` top-level package removed.
  Workflow dispatch (ex `detect_workflow`) and the per-workflow thin
  shells (`run_simulation`, `run_overview`, `run_mesh`,
  `run_calibration`, `run_batch`) are now in
  `hydromodpy/_cli/workflows.py`. Templates under `runners/templates/`
  were unused in production — dropped along with the one test that
  imported them.
- **BREAKING** (G07): extended exit-code contract adds
  `EXIT_DATA_ERROR=5` (returned by `hmp data check` when artefact
  validation fails, `hmp lock verify` on mismatch) and
  `EXIT_SOLVER_ERROR=6` (reserved). `hydromodpy._cli.helpers` is the
  authoritative module for CLI exit codes.
- **BREAKING**: imports relocated:
  - `hydromodpy.core.tools.raster_io` → `hydromodpy.core.io.raster_io`.
  - `hydromodpy.core.tools.geospatial` → `hydromodpy.core.io.crs`.
  - `hydromodpy.core.tools.filesystem.load_shapefile` →
    `hydromodpy.core.io.vector_io.load_shapefile`.
  - `hydromodpy.core.tools.log_manager` → `hydromodpy.core.logging`
    (re-exported from `hydromodpy.core.logging` package init).
- **BREAKING**: canonical package renames — no alias, no deprecation shim:
  - `hydromodpy.process` → `hydromodpy.physics`; the Pydantic
    configuration object `hmp.process` is now `hmp.physics` and all
    sub-imports (`hydromodpy.process.flow.*`,
    `hydromodpy.process.transport.*`, `hydromodpy.process.base.*`)
    moved accordingly.
  - `hydromodpy.simulation.results` → `hydromodpy.simulation.extraction`;
    solver-specific post-run extractors now live at
    `hydromodpy.simulation.extraction.extractors.*`.
- **BREAKING**: canonical class renames:
  - `SolverAdapter` → `SolverRunner` (both the Protocol in
    `hydromodpy.solver.base.protocol` and its duplicate in
    `hydromodpy.simulation.adapters.base`). Registry helpers keep their
    names; only the type alias changes.
  - `DataManagersPlanner` → `DataPlanner` (in `hydromodpy.data.planner`).
    `DataLoadPlan` and `DataManagersConfig` are unchanged.
  - `Geographic` → `CatchmentDelineation`; the module
    `hydromodpy.spatial.geographic.geographic` is renamed to
    `hydromodpy.spatial.geographic.catchment_delineation`. Public API:
    `hmp.Geographic` → `hmp.CatchmentDelineation`. `GeographicConfig`,
    `GeographicDerivedFeatures`, `GeographicCache`, and the package
    name `hydromodpy.spatial.geographic` are unchanged.
  - `hydromodpy.results.simulation.Simulation` (catalog view)
    → `hydromodpy.results.simulation.SimulationView`; the
    programmatic façade `hmp.Simulation` (in `hydromodpy.project`)
    keeps its name. Public API exposes `hmp.SimulationView` for
    immutable catalog-backed access and `hmp.Simulation` for
    `Simulation(config).run()` orchestration.
- **BREAKING**: `HydroModPyConfig` root config now forbids extra keys
  (`ConfigDict(extra="forbid", arbitrary_types_allowed=True)`). Unknown
  top-level TOML sections raise `ValidationError` rather than being
  silently ignored.
- `TimeSeriesValidationError`, `RasterConversionError`,
  `VectorConversionError` now inherit from the typed `DataError` /
  `DataContractViolation` hierarchy instead of bare built-ins.
- `hydromodpy.core.config.hydromodpy_config` no longer imports any
  non-core sibling at module top level; `core/` is a leaf of the
  import DAG (forward references + deferred `model_rebuild`).
- **BREAKING**: `*Schema` suffix dropped from every Pydantic config
  class. Renames:
  - `FieldBaseSectionSchema` → `FieldBaseSection`,
    `FieldHomogeneousSectionSchema` → `FieldHomogeneousSection`,
    `FieldHeterogeneousSectionSchema` → `FieldHeterogeneousSection`,
    `FieldVerticalProfileSectionSchema` → `FieldVerticalProfileSection`,
    `ResolvedFieldParamSchema` → `ResolvedFieldParam`.
  - `MeshCatchmentConfigSchema` → `MeshCatchmentConfig`,
    `MeshCatchmentRiversConfigSchema` → `MeshCatchmentRiversConfig`,
    `MeshCatchmentWatershedBoundarySmoothingConfigSchema` →
    `MeshCatchmentWatershedBoundarySmoothingConfig`,
    `MeshCatchmentWatershedOutsideCoarseningConfigSchema` →
    `MeshCatchmentWatershedOutsideCoarseningConfig`,
    `MeshCatchmentWatershedGeologyConformityConfigSchema` →
    `MeshCatchmentWatershedGeologyConformityConfig`,
    `MeshCatchmentWatershedBoundaryConfigSchema` →
    `MeshCatchmentWatershedBoundaryConfig`,
    `MeshCatchmentHydraulicPropertyMappingSchema` →
    `MeshCatchmentHydraulicPropertyMapping`,
    `MeshCatchmentHydraulicConductivitySchema` →
    `MeshCatchmentHydraulicConductivity`,
    `MeshCatchmentStorageCoefficientSchema` →
    `MeshCatchmentStorageCoefficient`,
    `MeshCatchmentHydraulicPropertiesConfigSchema` →
    `MeshCatchmentHydraulicPropertiesConfig`,
    `MeshCatchmentBatchOutputsSchema` → `MeshCatchmentBatchOutputs`,
    `MeshCatchmentBatchSectionSchema` → `MeshCatchmentBatchSection`.
  - `MethodComparisonVariantSchema` → `MethodComparisonVariant`,
    `MethodComparisonObservableSchema` → `MethodComparisonObservable`,
    `MethodComparisonSectionSchema` → `MethodComparisonSection`,
    `MethodComparisonFineRasterSchema` → `MethodComparisonFineRaster`.
  - `GeologySourceSchema` → `GeologySource`,
    `GeologyLandSeaSchema` → `GeologyLandSea`,
    `GeologyConfigSchema` → `GeologyConfigBlock` (existing
    `GeologyConfig` class in the same module already claimed the name).
  - `ZoneMeshingRefinementFamiliesSchema` →
    `ZoneMeshingRefinementFamilies`,
    `ZoneMeshingDomainBBoxSchema` → `ZoneMeshingDomainBBox`,
    `ZoneMeshingDomainPolygonSchema` → `ZoneMeshingDomainPolygon`,
    `ZoneMeshingDomainVectorSchema` → `ZoneMeshingDomainVector`,
    `ZoneMeshingDomainGeographicBoxBufferSchema` →
    `ZoneMeshingDomainGeographicBoxBuffer`,
    `ZoneMeshingDomainGeographicWatershedSchema` →
    `ZoneMeshingDomainGeographicWatershed`,
    `ZoneMeshingDomainGeographicWatershedBoxSchema` →
    `ZoneMeshingDomainGeographicWatershedBox`.
  No backwards-compatible alias is provided — callers must update
  imports.

### Removed
- **BREAKING** (G07): `hydromodpy/runners/` package deleted entirely.
  `detect_workflow()` and `runners/{simulation,overview,mesh,calibration,batch}.py`
  are replaced by `hydromodpy/_cli/workflows.py`. The unused
  `runners/templates/*.py` TOML-template renderers (used only in one
  unit test) are dropped.
- `hydromodpy/core/tools/geospatial.py` (moved to `core/io/crs.py`). The
  unused ``basin_area`` helper did not carry over.
- `hydromodpy/watershed/` package deleted in full. The legacy
  `Watershed` facade and its helpers (`Watershed`, `Settings`,
  `Hydraulic`, `Hydrography` alias) are gone — prefer
  `hmp.CatchmentDelineation` with `hmp.HydrographyManager`. Dependent
  helpers removed: `hydromodpy.core.tools.io_utils.extract_watershed`
  and `tests/regression/golden_utils.run_legacy_example_script`.
- `hydromodpy/data/runtime_loader.py` renamed to
  `hydromodpy/data/loader.py`. No alias. `load_variable(...)` is the
  new functional dispatch helper alongside
  `DataManagersRuntimeLoader`.
- `hydromodpy/data/common/base_field_manager.py` deleted. The
  `BaseFieldManager` abstract class now lives at
  `hydromodpy.data.base_manager` next to `BaseVariableManager`.
- `hydromodpy/data/common/base_manager.py` and
  `hydromodpy/data/common/base_config.py` moved one level up to
  `hydromodpy/data/base_manager.py` and `hydromodpy/data/base_config.py`.
  All in-tree callers updated — no backwards-compat shim.
- **BREAKING** (G05): `HOMOGENEOUS_ZONE` constant and the
  ``parameters.zone_id DEFAULT '_homogeneous'`` sentinel are gone. The
  default zone is now ``__global__``; callers must migrate or reset the
  workspace. `simulation_group.parameters` uses the new sentinel when
  flattening its pivot table, and `SimulationCatalog.write_parameters`
  inserts ``__global__`` when no zone is supplied.
- **BREAKING** (G05): `SimulationCatalog.export_package` now produces a
  single ``tar.zst`` file (``.hmp``) with a manifest and per-file
  SHA-256, instead of an unpacked directory. Readers that used to peek
  into ``<pkg>/simulation.duckdb`` or ``<pkg>/results.zarr.zip`` must
  decompress the archive first (`tarfile` + `zstandard`). Import
  validates every file against its manifest hash before touching the
  destination catalog — tampered archives now fail fast.

---

## [v0.4.0] - 2026-04-21

First release of the refactored architecture (branch `dev-refact_v2`).
Major version bump: HydroModPy v0.4.0 is a **breaking release** that
consolidates the 13 migration phases (P01–P13) plus the finalization
phases (F01–F08). External scripts pinned to 0.3.x require the
**Migration Guide** below.

Conformance to the 14 target architecture specifications
(`architecture_cible/*.md`) is certified by
`docs/developers/architecture_conformance_report.md`: 162/273 checkpoints
OK, 79 assumed gaps, 32 missing items requalified as v0.5 follow-ups. No
blocking debt remains — `hmp` CLI, `hydromodpy` Python API, pipeline
execution, calibration engine, and frontend schema hooks are all
operational on 1857 passing unit tests.

### Breaking Changes
- `SimulationCatalog.export_simulation` → `SimulationCatalog.export_package`
  and `SimulationCatalog.import_simulation` → `SimulationCatalog.import_package`.
  The `_package` suffix aligns with `architecture_cible/10_ux_cli_api.md`
  and disambiguates the per-variable
  `SimulationCatalog.export(sim_id, variable, fmt, path)` helper.
  No alias, no deprecation shim.
- Environment variables `HYDROMODPY_NO_DISPLAY` and `HYDROMODPY_NO_SAVE`
  removed. Display behaviour (saving figures, interactivity, output
  directory) is now controlled exclusively by the `[display]` TOML
  section.
- Calibration TOML simplified: the `[calibration]` section is now
  declarative (optimizer + objective + parameters) with the lightweight
  mode enabled by default.
- SIM2 client renamed: `hydromodpy.data.common.clients.sim2_inrae` →
  `hydromodpy.data.common.clients.sim2_meteofrance`;
  `Sim2InraeClient` → `Sim2MeteoFranceClient`;
  `INRAE_SIM2_BASE_URL` → `SIM2_BASE_URL`. The data source is
  Meteo-France (SAFRAN-ISBA surface reanalysis). Endpoint unchanged.
- `hydromodpy.core.backends` compatibility shim removed. Import
  `get_whitebox_backend` directly from
  `hydromodpy.spatial.delineation` instead.

### Added
- `examples/getting_started/` — minimal, self-contained synthetic
  Dupuit example driven by `hmp run project.toml`; no DEM or network
  download required.
- `docs/developers/design_patterns.md` — reference guide for the ten
  core patterns (Protocol Solver, Pipeline Step, Figure, Delineation
  Backend, Data Manager, Pydantic+Annotated Config, Calibration
  Adapter, Objective, Metric, Figure Protocol).
- `hmp.SimulationPlan` exposed on the public top-level API
  (`hydromodpy/__init__.py:__all__`) so advanced users can inspect the
  immutable plan produced by `SimulationPlanner` before execution.
- Pipeline orchestration primitives: `PipelineState`, `CheckpointStore`,
  `StepsLedger`, `DerivedRegistry` (see
  `docs/developers/glossary.md`).

### Changed
- README: paper-era example list replaced by a pointer to
  `examples/getting_started/` and `examples/projects/`.

### Removed
- Orphan module `hydromodpy.exceptions` (no production imports).
- Orphan modules `hydromodpy.simulation.settings`,
  `hydromodpy.simulation.forcing`, `hydromodpy.results.resample`,
  `hydromodpy.core.tools.folder_root`,
  `hydromodpy.workflow.pipelines.process_simulation`.
- Dead legacy `__getattr__` shim in `hydromodpy.process` (contract
  symbols were already re-exported at module top; the deprecation path
  was unreachable).
- Unused legacy pickle compatibility helpers under
  `hydromodpy.simulation.adapters.flow.legacy_compat`.
- Paper-era `examples_legacy/` tree (3+ GB of historical scripts and
  outputs, superseded by the new `examples/` and `validation_cases/`
  trees).
- Empty residual shells `hydromodpy/analysis/display/` and
  `hydromodpy/analysis/postprocess/` (content migrated to
  `hydromodpy/display/` and the pipeline extract/derive/export steps
  during P08).

### Fixed
- Restored coverage collection on the regression CI job after the
  headless env-var purge.

### Deprecated
- MODFLOW-NWT sunset plan documented in
  `docs/developers/nwt_sunset_plan.md`. NWT stays fully supported in
  v0.4 and will be retired after the MF6 Lake (LAK) module integration
  lands (target v0.5+). The duplication between
  `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  and `hydromodpy/solver/modflow6/flow_to_modflow_adapter.py` is kept
  deliberately rather than factored into `modflow_common/`.

### Migration Guide
Projects pinned to 0.3.x need the following one-time edits:

1. **Display env vars → `[display]` TOML section.** Drop
   `HYDROMODPY_NO_DISPLAY=1` / `HYDROMODPY_NO_SAVE=1` from scripts and
   CI pipelines. The `[display]` defaults are already non-interactive
   and save-enabled; otherwise set `save = false` /
   `interactive = false` in the project TOML.
2. **Catalog export/import rename.** Replace
   `catalog.export_simulation(sim_id, path)` with
   `catalog.export_package(sim_id, path)`, and
   `catalog.import_simulation(path)` with
   `catalog.import_package(path)`.
3. **Calibration section.** Replace nested legacy calibration blocks
   with the simplified `[calibration]` section: `optimizer`,
   `objective`, and `parameters` subkeys (see
   `examples/getting_started/project.toml`).
4. **SIM2 client import path.** Replace
   `from hydromodpy.data.common.clients.sim2_inrae import Sim2InraeClient, INRAE_SIM2_BASE_URL`
   with
   `from hydromodpy.data.common.clients.sim2_meteofrance import Sim2MeteoFranceClient, SIM2_BASE_URL`.
5. **Spatial delineation backend.** Replace
   `from hydromodpy.core.backends import get_whitebox_backend` with
   `from hydromodpy.spatial.delineation import get_whitebox_backend`.
6. **Orphan modules.** `hydromodpy.exceptions` was unused; define your
   own exception hierarchy if you caught anything from it. TOML
   `[postprocess]` blocks are accepted but ignored — migrate to the
   pipeline extract/derive/export steps.

---

## [v0.3.4] - 2026-01-04
### Added
- Added `install/requirements-docker-light.txt` for pip-only Docker/server installs without IDE or visualization dependencies.
- Added optional Dask handling in SIM2 (chunked xarray only when Dask is available).

### Changed
- HydroModPy now loads display modules only when display features are invoked.
- Dockerfile updated for a light production flow using pip requirements.

### Fixed
- Improved PROJ database detection and fallback (including rasterio data dirs) to reduce `proj.db` layout errors in containers.

---

## [v0.3.3] - 2025-12-03
### Added
- Lightweight conda environment option (`env_hydromodpy_light.yml`) and matching light dependency set in `pyproject.toml` for setups without VTK or Jupyter kernels.

### Changed
- Replaced the former `downslope` helper with `masstransfer` as the single surface routing engine.
- Standardized raster reads on `imageio.v2` and removed deprecation warnings.
- Refactored SIM2 processing for leaner memory use.
- Simplified vedo imports in visualization routines and centralized PyHELP imports inside `watershed_root`.
- HELP3O loading now retries/resolves paths more reliably during PyHELP runs.
- Replace 'imageio' by 'rasterio' to resolve deprecation.

### Fixed
- Pandas warnings in PyHELP CSV ingestion and daily output aggregation (removed deprecated args and axis-based groupby).
- Multiprocessing pools in PyHELP now use a spawn context to avoid fork-in-multithreaded warnings on Python 3.11–3.13.

### Removed
- `hydromodpy.modeling.downslope` module (functionality consolidated into `masstransfer`).

---

## [v0.3.2] - 2025-11-28
### Changed
- Reworked SIM2 workflow: coarse clip without reprojection to trim inputs, resample on that reduced dataset, then final clip/mask with reprojection for clean outputs without wasted time or RAM.
- `disk_clip` now accepts `.shp`, `.gpkg`, and `.geojson`, and SIM2 filename parsing keeps the full variable name before `_SIM2_`.

### Fixed
- `toolbox.load_to_xarray` reprojects when `dst_crs` is provided even without a mask, matching the new SIM2 flow and avoiding extra memory use.
- SIM2 resampling preserves encodings and applies masking with the reprojected DEM consistently.

---

## [v0.3.1] - 2025-11-14
### Changed
- Installation guide reorganized with ready-made command recipes, dual YAML options (runtime vs editable), and clearer guidance for conda-versus-pip setups.
- README now flags v0.3.1 as the stable release and the conda YAMLs pin Python 3.11–3.13 explicitly.
- Add spyder package to the conda environment for users of that IDE.

### Fixed
- `pyproject.toml` now lets setuptools auto-discover all `hydromodpy*` packages so `pip install hydromodpy` (and ReadTheDocs builds) no longer fail if optional submodules such as `hydromodpy.modeling.gr4j` are absent from the current branch.
- Pinned NumPy to >= 2.0 and restricted supported Python to >= 3.11, < 3.14 to avoid incompatibilities with other packages.

---

## [v0.3.0] - 2025-11-06
### Compatibility
- Runtime baseline jumps from Python 3.8.10 to the Python 3.11–3.13 series. Tested on Linux, macOS, and Windows.

### Added
- Logging system with `LogManager` class (replaces all `print()` statements).
- GitHub Actions pipeline for automated builds and PyPI publication.
- Single cross-platform conda environment file (`environment-conda.yml`) for Linux, macOS, and Windows.
- Automatic download of HELP3O binaries on first use (no Fortran compiler needed).
- `MANIFEST.in` for packaging executables, examples, and documentation.
- Pin `PROJ_DATA` and `PROJ_LIB` to the active pyproj data folder to avoid stale `proj.db` files.
- Override external `PROJ_DATA` paths that leave the environment or miss `proj.db` so the environment copy always loads (problem often caused by gdal).
- `pyhelp` CLI now exports `PYHELP_WORKDIR` and `help_example.py --workdir` to stop the Windows crash on Example 10.

### Changed
- Renamed package from `src` to `hydromodpy` following standard Python conventions.
- Replaced GDAL with rasterio for pip-only installation (tested with Python 3.13).
- First version available via `pip install hydromodpy`.
- Conda installation now fully automatic with single environment file (with only conda-forge channels, no pip dependencies).
- Updated all imports in examples (00-11) from `src` to `hydromodpy`.
- PyHELP now downloads pre-compiled binaries instead of requiring Fortran compilation.
- Logging supports three modes: "dev" (DEBUG), "verbose" (INFO), "quiet" (WARNING).
- Replaced deepdish with pickle for serialization.

### Removed
- Platform-specific environment files (`env_pyhelp-0.1_windows.yml`, `environment-crossplatform-3119.yml`).
- Fortran compilation requirements for PyHELP.
- Unused FTP-AQUIFER utility scripts.
- Hard-coded GDAL dependencies.
- Removed obsolete third-party packages (e.g., hydroeval, deepdish) to ensure compatibility with Python 3.11+.

### Fixed
- Normalized example folder names.
- Cross-platform file path handling.
- Suppressed verbose logging from third-party libraries (matplotlib, flopy, etc.).
- PROJ data synchronization in PyHELP NetCDF writer.
- macOS HELP3O binary extraction.

---

## [v0.2.0] - 2025-11-05
### Added
- Added MT3D-USGS support with new `Mt3dms`, `Masstransfer`, and `watershed.transport` modules, included Example 09, and provided executables for Linux, macOS, and Windows.
- Added the GR4J rainfall-runoff calibration toolbox with scripts, figures, and sample data under `src/modeling/gr4j`.
- Added the PyHELP land-surface coupling (API, CLI, preprocessing) together with Example 10 resources and a Windows-only environment file.
- Added Example 11 to run the full workflow from scratch without plots.
- Added the `test/01_test_non-regression` suite and reference outputs for regression testing.
- Added yearly intermittency plus MT3D seepage concentration and accumulated mass to the timeseries exports.
- Added platform-specific conda environment files for HydroModPy 0.1.

### Changed
- Updated `modflow.py` to support elevation-driven decay parameters, optional EVT extinction depth, and creation of the LMT link file when using MT3DMS.
- Updated the hydraulic configuration so it keeps the new decay settings and `exdp` value.
- Updated `modpath.py` particle seeding to center start points, respect `model_folder`, and align forward and backward runs.
- Expanded the `watershed_root` workflow with transport functions, a calibration results folder, MT3DMS helper modules, and the PyHELP preprocessing function.
- Improved `timeseries` handling so recharge and runoff accept scalars, series, or dicts while exposing the new MT3D metrics.
- Updated geographic and hydrography helpers to fall back on existing DEM rasters and clip optional stream inputs.

### Fixed
- SIM2 climate ingestion now uses the current Météo-France variable names and units and exposes the soil drought index.
- Watershed visualisations restore the DEM colour bar, scale bar, and labelled watershed overlay.
---

## [v0.1.0] - 2025-10-31
### Added
- **First official release** of the HydroModPy package.
- Established the initial project structure for hydrological/hydrogeological modeling workflows.
- Defined the versioning convention following **Semantic Versioning (vX.Y.Z)**.

---

[Unreleased]: https://github.com/HydroModPy/HydroModPy/compare/v0.4.0...dev
[v0.4.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.4...v0.4.0
[v0.3.4]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.3...v0.3.4
[v0.3.2]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.1...v0.3.2
[v0.3.1]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.0...v0.3.1
[v0.3.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/HydroModPy/HydroModPy/releases/tag/v0.1.0
