# Field Discretization Examples

This folder contains demo-only files for standalone SGrid/FieldParam
discretization workflows.

- `run_demo_config.py`: Pydantic schema used by the demo.
- `run_demo_config_2d.toml`: ready-to-run 2D demo config.
- `run_demo_3d_config.toml`: independent 3D demo config with exponential vertical profile.
- `case_runner.py`: orchestration helper and entrypoint for demo runs.
- `demo_top_bretagne_10km.tif`: demo raster input.
- `outputs/`: generated figures and outputs.

Data note:

- Demo configs now point to
  `examples/data/geology/GEO1M_brittany.shp`
  instead of the full France shapefile.
- This keeps the same workflow but reduces I/O and vector processing cost
  during discretization examples.

Note on outputs:

- The discretization core now computes a full `values_3d` array
  `(nlay, nrow, ncol)` for solver workflows.
- Existing demo figures deliberately remain plan-view and therefore use
  `values_2d` as planar reference visualization.
- 3D and section figures are generated through `case_runner.py` scenarios.
