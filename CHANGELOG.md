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

[Unreleased]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/compare/v0.2.0...dev
[v0.2.0]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/compare/v0.1.0...v0.2.0
[v0.1.0]: https://gitlab.com/Alex-Gauvain/HydroModPy/-/releases/v0.1.0
