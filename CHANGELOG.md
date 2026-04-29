# Changelog

All notable changes to this project will be documented in this file.

The format follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention
and this project adheres to [Semantic Versioning](https://semver.org/).

---

## About this file

This changelog lists every significant modification of the HydroModPy project,
from new features to fixes and internal updates.

Each release section includes the following standard categories:

- **Added** - for new features
- **Changed** - for updates in existing functionality
- **Deprecated** - for soon-to-be removed features
- **Removed** - for removed features or files
- **Fixed** - for any bug fixes
- **Security** - for security improvements

### How to update it

1. During development, document all notable changes under the **[Unreleased]** section.
2. When creating a new release (e.g., `v0.1.1`), move that content into a new section
   named `## [v0.1.1] - YYYY-MM-DD`.
3. Keep the `[Unreleased]` section empty to start recording changes for the next release.

---

## [Unreleased]

### Breaking (S00-05 hard-cut legacy)
- Removed `hydromodpy/_cli/legacy_calibration.py`; the deprecated
  `[model_calibration]` TOML section is no longer auto-renamed to
  `[calibration]`. Rename the section by hand.
- Removed the empty `hmp migrate` stub
  (`hydromodpy/_cli/commands/migrate.py`) and the
  `docs/developers/parquet_lakehouse_migration_guide.md` guide. Old
  workspaces (pre-v0.6) are no longer migrated; regenerate them.
- Removed `hydromodpy/core/tools/statistics.py` (RMSE/NSE/KGE helpers).
  Equivalent metrics live in `hydromodpy.calibration.metrics` and
  `objective_mapping`.
- Removed `tools/investigate_sloping_substratum_transient.py` (zero
  callers) and `validation_cases/update_reports.py` (with its dedicated
  unit test).
- Removed `hydromodpy_annex/distribution/` (re-export shim of
  `tools.mesh_bundle_viewer`).
- Removed `docs/readthedocs/source/architecture/overview/compatibility-facades.rst`
  (described modules that no longer exist).
- Removed dead aliases: `LocalStepSolveResult`, four boussinesq
  formulation aliases (`assemble_steady_mixed_complementarity`,
  `assemble_transient_mixed_complementarity`,
  `assemble_steady_head_only_regularized_partition`,
  `assemble_transient_head_only_regularized_partition`),
  `WatershedThresholdScanConfig`, three `*Schema` aliases in
  `gmsh_grid/zone_meshing/config.py`
  (`ZoneMeshingRefinementFamilySettingsSchema`,
  `ZoneMeshingRefinementHotspotSettingsSchema`,
  `ZoneMeshingRefinementGridSettingsSchema`), and
  `tests.regression.golden_utils.resolve_first_model_workspace`.
- Removed Python <3.11 fallbacks: five `try: import tomllib except: import tomli`
  blocks and three `except ModuleNotFoundError: from <bare_name> import …`
  script-mode shims in `spatial/field/core/`.
- Removed self-ignore line `.gitignore` from `.gitignore`.

### Changed
- Per-simulation `timeseries`, `budgets`, and `mass_balance` rows now live as
  Parquet files under `simulations/<uuid>.parquet/` instead of DuckDB tables
  inside `hydromodpy.duckdb`. DuckDB views with the original table names
  keep the read surface unchanged - every `SELECT ... FROM timeseries`
  call keeps working. See
  `docs/developers/parquet_lakehouse_architecture.md` for the layout and
  `docs/developers/parquet_lakehouse_concurrency.md` for the retry and
  atomic-rename patterns.
- `SimulationCatalog` now retries on `duckdb.IOException` at both connect
  time (`connect_with_retry`) and execute time (`@with_lock_retry`) on
  every write path. Short-lived cross-process lock contention resolves
  transparently instead of surfacing as an error.
- `hmp run <calibration.toml>` now drives real MODFLOW simulations through
  the new trial primitive (no more analytical mock). Each trial runs in
  `ExecutionRegistry.lightweight=True` mode, skipping Zarr/Parquet writes.
  Only the top-N iterations (via `save_runs = "best_n"`) get promoted to
  full simulations. See `docs/developers/calibration_guide.md`.
- `make_hot_simulator` now returns `(calibration_vector, raw_results)` so
  callers can persist selected series post-calibration without re-running
  the solver. `persist_calibration_result` renamed to `promote_trial`
  (deprecated alias kept for one release cycle).

### Added
- Calibration refactor - trial primitive plus step auto-invalidation:
  - `hydromodpy.simulation.execution.trial` with `TrialContext`,
    `prepare_trials`, `run_trial_light`, `promote_trial`.
  - `hydromodpy.pipeline.dependencies.earliest_affected_step` computes
    which pipeline step must re-run first from a set of override paths,
    using longest-prefix match on the new `config_sections` class var
    declared by each of the 12 pipeline steps.
  - `hydromodpy.calibration.metrics.build_metric_extractor` - RAM-only
    metric extractor for MODFLOW-NWT discharge (DRAIN budget aggregated)
    and head at observation cells.
  - `ExecutionRegistry.lightweight` flag gates Zarr / Parquet / catalog
    writes in steps 06 and 07.
  - `ParamsHashCache` preload from DuckDB at session start for
    cross-session trial deduplication.
- `hmp report <session_id>` - generates a self-contained HTML report
  under `<workspace>/reports/<session_id>/report.html` embedding the
  calibration session metadata plus the six calibration figures.
- Six calibration figures registered in the Display registry:
  `calibration_convergence`, `calibration_trace`, `calibration_landscape`,
  `calibration_posterior`, `calibration_objective_surface`,
  `calibration_pairplot`.
- Analytical calibration cases ported under `hydromodpy.calibration.cases`:
  `recession_brutsaert` (Brutsaert 1D recession) and `groundwater_1d`
  (Dupuit 1D aquifer). Both ship with synthetic chronicle builders + a
  `calibrate_<name>(method, ...)` dispatcher that hooks into
  `CalibrationEngine`.
- `hydromodpy.calibration.diagnostics` helpers (`convergence_rate`,
  `parameter_correlation`, `iterations_to_dataframe`).
- User guide: `docs/developers/calibration_guide.md` (replaces the two
  refactor prompts under the same directory).
- `hmp doctor` now reports the Parquet layout health (orphan directories,
  leftover legacy tables, per-sim Parquet counts).
- Unit tests covering atomic Parquet writes, view semantics, and 8-worker
  concurrent writes (`tests/unit/results/test_parquet_lakehouse.py`).
- ~130 new calibration tests across `tests/unit/calibration/`,
  `tests/unit/test_calibration_cli.py`, and
  `tests/regression/fast/calibration/` (including the Brutsaert golden
  regression for four optimization methods).

### Removed
- `_default_evaluator` (analytical mock) from the user-facing calibration
  path. Custom metrics are now supplied via the
  `objective = "module.path:fn"` escape hatch.
- `hmp migrate` subcommand (see commit `6857edb3`).

### Fixed
- `SimulationCatalog.write_*` methods are now tolerant of the DuckDB
  single-writer lock through the new retry decorator, fixing a latent
  bug where `hmp list` running concurrently with `hmp run` could raise
  `IOException`.

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
- Multiprocessing pools in PyHELP now use a spawn context to avoid fork-in-multithreaded warnings on Python 3.11-3.13.

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
- README now flags v0.3.1 as the stable release and the conda YAMLs pin Python 3.11-3.13 explicitly.
- Add spyder package to the conda environment for users of that IDE.

### Fixed
- `pyproject.toml` now lets setuptools auto-discover all `hydromodpy*` packages so `pip install hydromodpy` (and ReadTheDocs builds) no longer fail if optional submodules such as `hydromodpy.modeling.gr4j` are absent from the current branch.
- Pinned NumPy to >= 2.0 and restricted supported Python to >= 3.11, < 3.14 to avoid incompatibilities with other packages.

---

## [v0.3.0] - 2025-11-06
### Compatibility
- Runtime baseline jumps from Python 3.8.10 to the Python 3.11-3.13 series. Tested on Linux, macOS, and Windows.

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
