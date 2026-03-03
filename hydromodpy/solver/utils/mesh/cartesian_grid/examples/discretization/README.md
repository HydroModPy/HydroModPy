# Field Discretization Examples

This folder contains demo-only files for standalone SGrid/FieldParam
discretization workflows.

- `run_demo_2d.py`: lightweight CLI visualization script (2D panels, HSV colormap).
- `run_demo_3d.py`: dedicated visualization script (vertical center section,
  horizontal center section, and additional 1D profile).
- `prepare_brittany_geology_subset.py`: utility to build a Brittany-only geology
  subset from the France-wide shapefile for faster demo loading.
- `run_demo_config.py`: Pydantic schema used by the demo.
- `run_demo_config_2d.toml`: ready-to-run 2D demo config.
- `run_demo_3d_config.toml`: independent 3D demo config with exponential vertical profile.
- `case_runner.py`: accessory orchestration helpers for demo runs.
- `demo_top_bretagne_10km.tif`: demo raster input.
- `outputs/`: generated figures and outputs.

Data note:

- Demo configs now point to
  `data/Brittany_small_test_example/geology/GEO1M_brittany.shp`
  instead of the full France shapefile.
- This keeps the same workflow but reduces I/O and vector processing cost
  during discretization examples.
- To regenerate the Brittany subset from source data:
  `conda run -n hydromodpy python hydromodpy/solver/utils/mesh/cartesian_grid/examples/discretization/prepare_brittany_geology_subset.py --overwrite`

Note on outputs:

- The discretization core now computes a full `values_3d` array
  `(nlay, nrow, ncol)` for solver workflows.
- Existing demo figures deliberately remain plan-view and therefore use
  `values_2d` as planar reference visualization.
- `run_demo_3d.py` uses the same discretization core but renders a dedicated
  2-panel figure centered on `values_3d`.
- In `run_demo_3d.py`, colormap is `hsv`; normalization switches automatically
  to logarithmic when value spread is greater than one order of magnitude.
- `run_demo_3d.py` also writes a second figure with the **same layout**
  (orthogonal sections + profile), but for the FieldParam projected on SGrid at
  `depth=0` and extruded over layers (pre-vertical-correction view).
