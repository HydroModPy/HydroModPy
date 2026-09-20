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
2. When creating a new release (e.g., `v1.1.0`, `v2.0.0a1`, `v2.0.0b1`,
   or `v2.0.0rc1`), move that content into a new section named
   `## [vX.Y.Z] - YYYY-MM-DD` or the matching pre-release tag.
3. Keep the `[Unreleased]` section empty to start recording changes for the next release.

---

## [Unreleased]

### Removed
- `[modflownwt.tgrid]` is gone from the schema, following `[modflow6.tgrid]`.
  No backend ever read it back: `apply_explicit_time_window_to_tgrids()`
  overwrote it from `[simulation.time]` and nothing consumed the result, so a
  file could declare `itmuni = "days"` next to a run executing in seconds.
  `hmp doctor --fix-config` drops the section, at the root and under a
  comparison or testbed overlay, which the MODFLOW 6 migration did not reach.
- `hydromodpy/discretization/` was deleted. `[modflownwt.tgrid]` was its last
  importer, through `TMeshConfig`; `TmeshGenerator` and `TimeGrid` had already
  been unreachable since `build_temporal_discretization()` lost its caller.
  Chronicle-driven stress periods (`genmtd = "from_chron"`) and per-period
  `ntsp`/`tsmult` go with it: `[simulation.time]` expresses a regular
  calendar-aware step, and restoring variable periods means extending
  `ResolvedSimulationTimeGrid`, not reviving a parallel temporal model.

### Changed
- A staged calibration declaring `uncertainty.method = "linearized"` now gets a
  width per phase, taken around that phase's own optimum. It got none at all:
  the dispatch that builds one lives in the non-staged route, so the search was
  paid for in solver hours and nothing came back. Of the three declared
  methods two were already honoured per phase - `cost_profile` inside the core
  the staged route calls, `multistart` reimplemented by the staged runner - and
  `linearized` was orphaned by anatomy, not by meaning.
- A width taken after an earlier phase froze parameters is conditional on that
  freeze, and the Methods paragraph says so instead of reporting it as an
  absolute. It also tells a width that was built and is conditional from one
  that was never built: "Reported parameter uncertainty is conditional on the
  following" covers the first, "No parameter uncertainty was built for" the
  second. A run whose phases were all reused from disk used to claim a reported
  uncertainty where there was none.
- A phase none of whose outputs can name a station keeps its report instead of
  losing it. `CalibOutputNetwork` carries no `observes` field, so the steady
  stage of `matching_hydrographic_network` - the only registered protocol -
  holds an output, holds no station and can never hold one; asking for a width
  there ended the whole staged run after the steady search had been paid for.
  An output that could have named a station and did not is still a document
  mistake and still fails loudly.
- `hmp calibrate --check` counts two refusals on a document declaring phases
  that it did not count before, and exits non-zero where it exited 0. The
  burn-in guard for `method = "linearized"` skipped every phased document,
  since no width was built for one, and now applies phase by phase. And the
  refusal for an output naming no station is raised once per search rather than
  once per file, so a five-phase document says which phase cannot carry a
  width. On a single-metric phase the message names the real mechanism, a phase
  scored on `variable`/`objective` inherits none of the calibration's outputs,
  instead of pointing at an `observes` the schema refuses on that phase.
- Example 04 renders eight figures instead of twenty. What went were the
  duplicates, not the diagnostics: four comparison panels folding the same 36
  residuals, a duration curve over 36 monthly points, a boxplot of three
  values per month, a budget bar summing timestep rates, and three network
  maps the confusion map already covers. Every figure drawing one instant now
  draws the same one, October 2002, the driest month, rather than the default
  last timestep, a December whose network is nearly full.
- A NetCDF export writes a layered field as one variable per layer, named
  `<var>` on a single-layer model and `<var>_layer<N>` above it, and no longer
  carries a `layer` dimension. QGIS cannot read a third dimension and most
  catchment models run on one layer. `import_netcdf_fields` stacks the layers
  back, so a round trip through the file is unchanged for everything but a
  single-layer field, which comes back without its layer axis.
- `hmp data export --list` names the fields a run exposes. It listed the
  geographic rasters, the vector features and the runs, but never the field
  names `--var` expects, so the only list that answers "what can I export" was
  the one it did not print. It also says which run it read, and reads the one
  `--sim` names when given, else the last live one: a trashed run was silently
  becoming the source.
- `simulation.time.substeps_per_period` documents what its default costs. One
  backward-Euler step per stress period moves the monthly discharge by 4 to
  28 % against a refined run on a seasonally recharged hillslope drained by DRN
  cells, across the whole plausible bedrock range, and a calibration scored on
  discharge absorbs that into the fitted parameters. The default stays at 1:
  the right count is a property of the model (`tau = L^2 S / (K b)` against the
  period length) and the solver cost is linear in it, so raising it silently
  would rewrite every existing result and multiply every calibration budget.
  A validation case now states the size of the drift.
- A calibration declaring `variable` and `objective` is now refused before its
  session exists rather than at every trial. Two loaded gauges without
  `calibration.observed_station_id` used to build an extractor, write a session
  row, spend the whole search budget and fail each trial with the same message;
  the refusal now names the two candidates while `hmp calibrate` is still
  reading the document.
- A trial that asks a built metric extractor for another `variable` or another
  `objective` is refused instead of silently scored. The producer, the observed
  records and the gauge the search follows are all chosen when the extractor is
  built, so a criterion renamed at call time reported a cost under a key the
  session never recorded.
- A solver serving an empty per-station discharge series now fails the trial
  with the same message the head and lake routes already used, naming the
  station, rather than the `no overlapping samples` message of the alignment
  step. The head and lake messages gain that station name with it, and the
  lake one now says `lake_level` where it said `lake stage`.
- A linearized parameter width is refused when the calibration it is taken
  around drops leading samples. `[calibration].warmup_periods`, and a block's
  own `warmup`, truncate each output before the cost is computed; the residual
  at each observation is not truncated and two blocks may drop different
  counts, so the covariance described a window the search was told to ignore.
  `hmp calibrate --check` names it before anything solves. A search that ran
  anyway keeps its report and loses only the width, the way every other
  no-width path already behaved.

### Fixed
- An objective block scoring several outputs checks each output's length
  against its own record, instead of checking the two concatenated totals. Two
  outputs individually wrong - twenty simulated values against thirty observed,
  then forty against thirty - sum to sixty on both sides and passed, while the
  metric scored the second output's first ten values against the first one's
  last ten. Measured: no block in `examples/projects/`, `tests/validation/` or
  `tests/e2e/` scores more than one output, so no existing result moves. The
  refusal names the output and both lengths, counted after the burn-in, which
  is what the metric receives.
- `hydrograph_log_nse` wrote its note across its own legend: pinned to the
  upper left, its longest line reaches the upper right whatever the axes width.
  The note sits on the log floor, a band the limits leave empty by
  construction.
- A NetCDF export was unusable in QGIS. Three causes, all in
  `results/exporters/netcdf.py`. The file georeferenced itself the CF way, a
  `crs` variable holding `crs_wkt`; MDAL, which is what QGIS opens a UGRID mesh
  with, looks up one variable by name and parses WKT1 only, so it kept no CRS
  and QGIS drew the mesh in the project CRS, nowhere near the catchment. A
  field stored per layer was written as one `(time, layer, face)` array, which
  MDAL ignores outright: `drain` simply did not appear among the dataset
  groups. And the face centroids, undeclared on the mesh variable, read as two
  datasets to plot. Checked against QGIS 3.x: the mesh now loads in EPSG:2154
  with one group per field and 36 steps each.
- Re-exporting a NetCDF onto a file QGIS still had open truncated it to zero
  bytes: netCDF4 truncates before it writes and HDF5 then failed on the lock.
  The write goes to a neighbouring file and is renamed into place, so a failed
  export destroys nothing and an open layer keeps reading what it has.
- `hmp data export` refused every per-cell budget field. Its own field filter
  rebuilt the "what is readable here" rule and looked at the store root and
  `derived/` only, so `drain` and `recharge`, which live under `budget/`, were
  reported as not exportable while `hmp.export()` wrote them without trouble.
  The filter now reads `run.array.list_fields()`, the single source of truth
  the readers already share.
- CI no longer runs the Whitebox-backed tests inside an xdist worker. The native
  binding dies outright when several DEM workflows share one long-lived worker,
  and the `xdist_group` that stops two workers touching the backend at once is
  exactly what puts them on the same node; `Tests / fast marker py3.12` lost
  `gw1` on `main` this way. Every parallel step in `main-ci`, `ci-weekly` and
  `ci-nightly` now excludes them and a serial step runs them, and a contract
  test parses the workflows so the split cannot drift back.
- `test_run_geographic_case_river_network_regression.py` was still listed in the
  Whitebox xdist group after being deleted in 298c08b9d, so the entry guarded
  nothing.

### Fixed
- MODFLOW 6 adaptive time stepping targeted the wrong stress period. FloPy
  converts an ATS `iper` to 1-based when it writes the file and the builder was
  already 1-based, so every record landed one period late and the last one fell
  off the end of the simulation. The first transient period never got ATS at
  all.
- Adaptive time stepping no longer discards the requested sub-stepping. MF6
  ignores the TDIS NSTP of a period ATS covers, and the record declared
  `dt0 = dtmax = perlen`, so a run asking for ten steps per period got one:
  0.0481 m of RMSE against the erfc closed form instead of 0.0035 m. Both bounds
  are now the step `simulation.time.substeps_per_period` asked for, so ATS can
  only cut below it, which is the failure recovery it exists for.
- `hmp doctor --fix-config` reads a config carrying a byte-order mark. tomlkit
  parsed the BOM as an empty key on line 1, so the whole fix aborted and nine
  validation configs in this repository could not be migrated at all.
- Two example report builders read `firstpersteady` from a solver `tgrid`
  section that never held it, and the Nancon sweep script wrote it into the
  configs it generates, producing files the runtime refuses. All three now use
  `[flow].first_period_steady`.
- MODPATH pathline and endpoint times are now converted to the unit the
  `particles` group declares. The MODFLOW-NWT extractor stored raw model time,
  seconds, while labelling it `days`, so every stored travel time and every
  residence-time figure built from it was off by a factor 86400.
- `ITMUNI` is now read from the first non-comment record of a MODFLOW DIS file,
  where it actually sits. The previous reader parsed the LAYCBD line below it
  and always fell through to its default, so a MODFLOW-NWT run declaring
  anything but seconds had its calibration fluxes left unscaled.
- The MODFLOW 6 PRT readers no longer fall back to `DAYS` when a run declares
  no time unit. An undeclared unit now means `SIMULATION_TIME_UNIT`, the unit
  the launcher builds every run in.

### Removed
- `DomainGeographicContext.river_mesh_trace` and the direct
  `CatchmentDelineation.river_mesh_trace` runtime attribute were removed.
  Mesh river constraints now read `GeographicDerivedFeatures.rivers.river_mesh_trace`
  or an explicit `river_trace`; the in-memory mesh config source is now
  `rivers.source = "geographic_features"` instead of `"domain_geographic"`.
- Generic testbed input spellings `[[testbed.variant]]`,
  `[[testbed.variant_from_catalog]]`, `TestbedConfig(variants=...)`, and
  `TestbedConfig(catalog_variants=...)` are no longer supported. Use
  `[[testbed.case]]`, `[[testbed.case_from_catalog]]`,
  `TestbedConfig(case=...)`, and `TestbedConfig(case_from_catalog=...)`.
- Generic testbed outputs no longer write the legacy compatibility keys
  `variant_id`, `variant_label`, `variant_count`, or `variant_from_catalog`.
  Read `case_id`, `case_label`, `case_count`, and `case_from_catalog`
  instead.
- Removed the application-level config compatibility aliases under
  `hydromodpy.core`. Use `hydromodpy.config.HydroModPyConfig` and
  `hydromodpy.config.schema_export` instead.

### Changed
- Simulation identity keys renamed. `[simulation].run_id` and
  `[simulation].on_collision` are removed and now hard-fail under
  `extra="forbid"`. Use `[simulation].name` for the run identity and
  `[simulation].if_exists` for name-collision behaviour. `if_exists`
  defaults to `version` (mint the next `stem.vN`), replacing the old
  `replace` default; `replace` and `fail` remain available. `hmp doctor
  --fix-config FILE.toml` migrates old keys in place.
- Unstructured MODFLOW 6 grids now build a Voronoi/PEBI dual by default
  (exact CVFD orthogonality, about half the cells, XT3D off). The new
  `grid_dual` field controls this; set `grid_dual = "triangle"` to restore
  the previous triangle DISV grid. Upgrading an existing unstructured
  MODFLOW 6 project changes its heads and budgets, and any calibration
  `params_hash` cache must be invalidated after the upgrade to avoid
  reusing stale objectives. MODFLOW-NWT (structured DIS) and Boussinesq
  are unaffected.
- Raster / VTU / shapefile auto-export now defaults to the last timestep
  instead of the first. Set `[export].times = "first"` to keep the previous
  behaviour.
- Documented the release policy for SemVer/PEP 440 versions, alpha/beta/rc
  pre-releases, the new `main` default line, the frozen `archive-v1` branch,
  release branches, tags, and GitHub Releases.
- Prepared the v2 line as `2.0.0a1` and updated project metadata, docs links,
  source links, and GitHub workflow branch filters from `master` to `main`.
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
- MODFLOW 6 Lake (LAK) package support: model one or several lakes/reservoirs
  as advanced boundary conditions with stage, bathymetry abacus, and bed
  leakance, driven from the `[flow]` boundary configuration. LAK is a
  MODFLOW 6 backend capability.
- Streamflow Routing (SFR) support on the MODFLOW 6 backend, including
  SFR-to-lake water movers (MVR) so routed streamflow can feed a LAK lake.
- Horizontal flow barrier support, including a dam cutoff wall (HFB), to
  reduce flow across a mapped line such as a grouting curtain under a dam.
- Lake bathymetry bed carving: a bathymetry raster can lower the MODFLOW 6
  cell bottoms under a lake so the aquifer grid follows the reservoir bed.
- Lake-level calibration: calibrate against an observed MODFLOW 6 LAK stage
  series (`variable = "lake_level"`) in addition to discharge and head.
- Top-level `[export]` configuration section promoting the raster / VTU /
  shapefile / time-series export toggles to a first-class config block.
- New geographic `domain_extent` option (`box`, `watershed_buff`,
  `watershed`) to select the modelled domain surface, and a mesh
  `lake_refinement` block to refine cells around lakes and dams.
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
