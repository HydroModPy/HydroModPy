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
- Planned updates and improvements for future releases.

### Fixed
- HydroModPy now pins `PROJ_DATA`/`PROJ_LIB` to the active environment's pyproj data directory on import, preventing accidental use of stale global `proj.db` copies.
- Added detection that overrides user-defined `PROJ_DATA` values pointing outside the active environment or to missing `proj.db` files, ensuring conda/venv-specific databases are always preferred.
- PyHELP CLI now propagates the working directory via `PYHELP_WORKDIR`, and `help_example.py` also accepts `--workdir`, fixing the Windows crash when launching example 10 manually.
- PyHELP automatically downloads and extracts the Windows bundle (`HELP3O_*_bundle.zip`) so that MinGW runtime DLLs ship alongside `HELP3O.cp***.pyd`.

---

## [v0.3.0] - 2025-11-06
### Added
- Logging system with `LogManager` class (replaces all `print()` statements).
- GitLab CI/CD pipeline for automated builds and PyPI publication.
- Single cross-platform conda environment file (`environment-conda.yml`) for Linux, macOS, and Windows.
- Automatic download of HELP3O binaries on first use (no Fortran compiler needed).
- `MANIFEST.in` for packaging executables, examples, and documentation.

### Changed
- Renamed package from `src` to `hydromodpy` following standard Python conventions.
- Replaced GDAL with rasterio for pip-only installation (tested with Python 3.13).
- First version available via `pip install hydromodpy`.
- Conda installation now fully automatic with single environment file.
- Updated all imports in examples (00-11) from `src` to `hydromodpy`.
- PyHELP now downloads pre-compiled binaries instead of requiring Fortran compilation.
- Logging supports three modes: "dev" (DEBUG), "verbose" (INFO), "quiet" (WARNING).
- Replaced deepdish with pickle for serialization.
- Updated copyright years to 2023-2025.

### Removed
- Platform-specific environment files (`env_pyhelp-0.1_windows.yml`, `environment-crossplatform-3119.yml`).
- Fortran compilation requirements for PyHELP.
- Unused FTP-AQUIFER utility scripts.
- Hard-coded GDAL dependencies.

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

[Unreleased]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/compare/v0.3.0...dev
[v0.3.0]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/compare/v0.2.0...v0.3.0
[v0.2.0]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/compare/v0.1.0...v0.2.0
[v0.1.0]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/releases/v0.1.0
