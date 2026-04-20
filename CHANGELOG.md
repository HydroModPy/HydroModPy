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
