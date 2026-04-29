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

---

## [v1.0.0] - 2026-04-29

First stable release. Closes the v0.6 architecture rupture started in
v0.5.0 (S01..S05) and lands the security / release-engineering hardening
of S06 plus the final naming sweep of S07. All `[Unreleased]` content
since v0.5.0 lands here. No alias, no shim, no deprecation path.

### Breaking

#### Module / class renames (S07)
- `hydromodpy._cli` → `hydromodpy.cli` (S07-01). The CLI is a public
  surface; the leading underscore was misleading. Update any external
  import (`from hydromodpy._cli...` → `from hydromodpy.cli...`). Entry
  points `hmp` and `hydromodpy` are unchanged.
- `hydromodpy/solver/modflow_nwt/modflow/` → `hydromodpy/solver/modflow_nwt/nwt/`
  and class `Modflow` → `ModflowNwt` (S07-02). Both backends are
  MODFLOW; the `modflow/` segment was ambiguous. Update imports
  (`from hydromodpy.solver.modflow_nwt.modflow ...` →
  `from hydromodpy.solver.modflow_nwt.nwt ...`) and references to the
  class (`Modflow` → `ModflowNwt`). Top-level export
  `hydromodpy.Modflow` is now `hydromodpy.ModflowNwt`.
- `hydromodpy/solver/boussinesq/extractors/output.py` → `flow.py` and
  `hydromodpy/solver/gr4j/extractors/output.py` → `flow.py` (S07-03).
  Symmetry with the MODFLOW family: every flow extractor is now named
  `flow.py`. The classes `BoussinesqOutputAdapter` and
  `GR4JOutputAdapter` are unchanged; only the module path moved.
- `hydromodpy/calibration/cli.py` → `hydromodpy/calibration/runner.py`
  (S07-04). The module is reached through `hydromodpy.cli`, not as a
  CLI itself; `runner` reflects its real role. Update imports
  (`from hydromodpy.calibration.cli ...` →
  `from hydromodpy.calibration.runner ...`).
- `hydromodpy/data/lockfile.py` → `hydromodpy/data/data_freeze.py` and
  `hydromodpy/results/provenance.py` → `hydromodpy/results/array_fingerprint.py`
  (S07-05). The module names now reflect their concrete role
  (input-data freeze; per-array fingerprint). Internal symbols
  (`LockedArtifact`, `LOCKFILE_NAME`, `archive_lockfile`,
  `read_lockfile`, `write_lockfile`, …) are unchanged: they still
  describe the on-disk `.lock` artifact.

#### Serialization / security (S06)
- User-controlled `pickle.load` paths replaced with HMAC-signed pickle
  for trusted internal artefacts and JSON for untrusted boundaries
  (S06-06). Loading a pre-v1.0 unsigned pickle now raises. Re-run the
  pipeline once to regenerate the artefact under the new format.
- `[hmac]` workspace section is required for signed-pickle paths; the
  key is generated on first run and stored in the workspace.

#### Packaging / runtime
- Solver binaries are no longer bundled in the wheel (S06-02). They
  download lazily into `~/.cache/hydromodpy/bin/` on first solver run.
  CI / offline setups must call `hmp install-binaries` upfront.
- Runtime dependencies now carry explicit upper bounds (S06-03).
  Editable installs that previously pulled the latest minor of every
  dep will resolve to the pinned ranges; bump the pin in
  `pyproject.toml` if a newer version is required.
- `pytest` was dropped from the runtime `dependencies` list (S06-03);
  install it via the `test` extra (`pip install hydromodpy[test]`).

### Added
- `SECURITY.md` with a single-tenant scientific-desktop threat model
  and a coordinated-disclosure address (S06-05).
- `RELEASE_POLICY.md` describing the OIDC-backed PyPI publish flow
  (S06-07). `publish.yml` now uses Trusted Publishers (no long-lived
  PyPI token).
- Multi-stage Dockerfile + `docker-build` GitHub Actions workflow
  (S06-04). The previous Dockerfile was non-functional.
- `dependabot.yml` (weekly) plus `pip-audit` lint gate and `gitleaks`
  pre-commit + CI hooks (S06-08).
- Wheel-smoke job, baseline `mypy` type-check, and CycloneDX SBOM
  generation in CI (S06-09).
- CI lint gate asserting `__all__` matches `_LAZY_IMPORTS ∪ _MODULE_EXPORTS`
  in the public top-level package (S06-12).
- CI lint gate sealing the CLI boundary: only `_cli` may import the
  CLI subsystem outside `__main__` (S06-13).

### Changed
- HMAC-signed pickle is now the canonical in-process serialization
  format for trusted artefacts (S06-06); JSON is used at every
  untrusted boundary.
- Tests sweep (S06-10): 18 hollow assertions strengthened, 3 stale
  doc-gallery skips dropped, mock backends replaced with the real
  `WhiteboxStubBackend`. 14 `gmsh_grid` tests migrated to `tmp_path`
  and the root `scratch_tests/` directory deleted (S06-11).

### Removed
- `scratch_tests/` directory at the repo root (S06-11). Stray fixtures
  now live under `tests/.../tmp_path` parametrisation.

### Migration guide

Apply these search/replace rules to a checkout pinned at v0.5.0 to
move forward to v1.0.0:

| Old import / name                                            | New import / name                                     |
|--------------------------------------------------------------|-------------------------------------------------------|
| `from hydromodpy._cli ...`                                   | `from hydromodpy.cli ...`                             |
| `from hydromodpy.solver.modflow_nwt.modflow ...`             | `from hydromodpy.solver.modflow_nwt.nwt ...`          |
| `hydromodpy.solver.modflow_nwt.nwt.Modflow`                  | `hydromodpy.solver.modflow_nwt.nwt.ModflowNwt`        |
| `hydromodpy.Modflow`                                         | `hydromodpy.ModflowNwt`                               |
| `from hydromodpy.solver.boussinesq.extractors.output ...`    | `... .extractors.flow ...`                            |
| `from hydromodpy.solver.gr4j.extractors.output ...`          | `... .extractors.flow ...`                            |
| `from hydromodpy.calibration.cli ...`                        | `from hydromodpy.calibration.runner ...`              |
| `from hydromodpy.data.lockfile ...`                          | `from hydromodpy.data.data_freeze ...`                |
| `from hydromodpy.results.provenance ...`                     | `from hydromodpy.results.array_fingerprint ...`       |

Other actions:

- Re-run any pipeline that produced pre-v1.0 pickle artefacts: legacy
  unsigned pickles no longer load (S06-06). The first run regenerates
  them under the HMAC-signed format.
- Install solver binaries explicitly in offline / CI environments:
  `hmp install-binaries` (the wheel no longer bundles them, S06-02).
- If your environment relied on the implicit `pytest` runtime
  dependency, install it via the `test` extra:
  `pip install hydromodpy[test]` (S06-03).
- Bump pinned ranges in `pyproject.toml` if a newer minor of a
  runtime dep is required (S06-03 added explicit upper bounds).

### Finish phase (S08)

Pre-tag remediation pass that lands the architecture target (94% → near-complete).
24 sessions (S08-00..S08-23) closing partial / blocked items inherited from
S04..S07 and trimming residual drift before the v1.0.0 cut.

- **P0 architecture (S08-00..S08-09)**: extract `master_config/` package out of
  `core/config` (S08-05) and break the 16 TYPE_CHECKING leaks
  `core → solver/data/spatial/...` (S08-06). Strict zero on `test_annex_one_way`;
  `test_layer_matrix` strict pass deferred (S08-09 BLOCKED — requires R0/R4-B
  base-helper extraction `master_config → core/config_base/`, scoped post-v1.0).
- **Workflow consolidation (S08-23)**: collapse 18 absorbed step modules into
  the unified workflow runner; drop `pipeline/` planning layer in favour of
  `workflow/`.
- **Cleanup sweep (S08-10..S08-22)**: drop calibration JSONL legacy export,
  unused `_LEGACY_STATION_EXPORT_DEFAULTS`, deprecated `climatic/` mentions in
  docs, and the last alias re-exports across `data/`, `results/`, `display/`.

Per-session reports: `unified_architecture/refactor_state/done/S08-*.md`.

---

## [v0.5.0] - 2026-04-29

This release lands the v0.6 architecture rupture: a strictly layered
DAG, no aliases, no legacy shims. Sessions S01..S05 of the
`unified_architecture/PLAN_ACTION.md` plan.

### Breaking
- Cross-package imports of `_<name>` modules / sub-packages are now
  forbidden by lint and CI; private helpers live behind their package.
- `core/` is the kernel leaf: it no longer imports any sibling layer
  (not even under `TYPE_CHECKING`).
- Solver backends are independent: `solver/modflow6/` and
  `solver/modflow_nwt/` no longer cross-import. The shared surface
  moved to `solver/modflow_common/` (S01-14, S01-15).
- `pipeline/` is being absorbed into `workflow/`. New files in
  `pipeline/` are forbidden.
- Top-level `hmp.*` no longer re-exports internal modules upward
  (S00-03). Use the canonical import path.
- Project, SimulationCatalog, MF6 backend, analysis batch/comparison,
  mesh bundle, results catalog, and field_param helpers were split
  into sub-packages. Direct imports of removed god-class symbols
  break (S03-01..S03-13).
- `SolverRunner` triple-protocol collapsed into a single
  `SolverAdapter` (S05-04).
- Twelve short Pydantic aliases dropped along with `Modpath7` from the
  public API (S05-01).
- Twelve Pydantic validators retyped to `Literal` / `Field(ge, le)`,
  removing hand-written `_validate_*` callbacks (S05-08, S05-09,
  S05-12).
- `Length` / `FlowRate` Pydantic fields now declared via
  `pydantic-pint`; bespoke validators dropped (S05-08).
- `extra="forbid"` enforced everywhere on `BaseModel`; passing an
  unknown TOML / kwarg key now raises (S05-07).
- `logging.getLogger` banned via `TID251`; every module-level logger
  goes through `hydromodpy.core.logging.get_logger` (S05-06).
- Workflow + solver adapters now raise typed `HMPY*Error` exceptions
  in place of vanilla `raise` / `RuntimeError` (S05-05).
- `workflow/orchestrator.execute_simulation` removed; orchestration
  goes through `Project.run` and `Pipeline` (S02-07, S02-08).
- `pipeline.pipeline` renamed to `workflow.runner`,
  `workflow.pipeline` renamed to `workflow.orchestrator` (S02-03).

### Added
- `Project.mesh()`, `Project.report()`, top-level `hmp.mesh()` /
  `hmp.report()` shortcuts (S05-11).
- `from_toml` / `from_json` / `from_dict` factories on `Project`,
  `SimulationCatalog`, `Run`. The `[calibration]` TOML section now
  loads through this path (S05-10).
- `FlowWellForcingConfig` discriminated union (S05-12).
- ML access pattern: `runs_environment` and `Catalog.training_split`
  (S04-16).
- `Run.summary(json=False)` for compact metadata snapshot (S04-14).
- `Run.dataset(variable=None)` returning a `xugrid.UgridDataset`
  (S04-07).
- `Catalog.worst` / `Catalog.rank`; `hmp best` / `hmp worst` collapsed
  into `hmp rank` (S04-13).
- `Catalog.delete(remove_storage=True)` cascade (S04-12).
- CSV / NetCDF / Zarr field importers (S04-10).
- `Grid` protocol + topology-aware grid wrappers (S04-08).
- `field_registry` boundary validation with `UnknownFieldError`
  (S04-09).
- Layer-matrix CI gate in xfail mode (`tests/unit/architecture/`,
  S00-02).

### Changed
- `Project` god-class split into `project/phases` + `project/accessors`
  modules (S03-03).
- `hydromodpy.core.io` now hosts the PROJ bootstrap (opt-in) and the
  DuckDB retry helper, replacing the `tools/` and `results/_db_retry`
  copies (S05-02, S01-02).
- Root sections are single-sourced from `HydroModPyConfig.model_fields`
  (S05-03).
- Metrics canonicalised around `results/metrics.py`, dropping
  duplicates across `core/tools` and `analysis` (S04-15).
- Run / catalog typing strengthened via `results/contracts` (S04-06).
- `core/grid_reference.GridReference` lifted out of `spatial` (S01-06).
- `ResultsConfig` moved to `core/config/results_config` (S01-04).
- `overview_config` split into `display/overview/config` and
  `core/contracts/overview` (S01-03).
- `compare` split into `compare_pair`, `compare_methods`, and
  `workflow_context` (S04-05).

### Removed
- `LocalStepSolveResult` and four boussinesq formulation aliases
  (S00-05).
- Empty `hmp migrate` stub kept around for nostalgia.
- `core/tools/statistics.py` (use `calibration.metrics`).
- Five `try: import tomllib except: import tomli` blocks plus three
  bare-name script-mode shims in `spatial/field/core/`. Python &lt; 3.11
  is no longer supported (S00-05).

### Fixed
- Calibration `engine.run` now wrapped in `try / except / finally`
  so partial sessions still flush their cache (S04-01).

---

## [v0.4.0] - 2026-04-28

First release of the parquet lakehouse + calibration trial primitive.
Picks up the `[Unreleased]` backlog accumulated since `v0.3.4`.

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
  the solver. `persist_calibration_result` renamed to `promote_trial`.

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
- `hmp migrate` subcommand.

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

[Unreleased]: https://github.com/HydroModPy/HydroModPy/compare/v1.0.0...dev
[v1.0.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.5.0...v1.0.0
[v0.5.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.4.0...v0.5.0
[v0.4.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.4...v0.4.0
[v0.3.4]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.3...v0.3.4
[v0.3.2]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.1...v0.3.2
[v0.3.1]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.0...v0.3.1
[v0.3.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/HydroModPy/HydroModPy/releases/tag/v0.1.0
