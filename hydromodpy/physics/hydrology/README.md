# physics/hydrology

The models that make a recharge from the weather, before the groundwater solve.

## Folders

1. `soil_reservoir/` is the daily soil reservoir. `config.py` is what `[flow.sinks_sources.recharge.soil]` can say, with each bound and its refusal in two tables. `kernel.py` is the arithmetic, one function per equation with its reference. `simulation/soil/` runs it on the loaded grids.
2. `synthetic/` makes synthetic precipitation, inflow and recharge series for demonstrators and tests.
3. `pyhelp/` is the PyHELP recharge model (MIT licence). `core/` is the model code, kept in its original style, and `preprocessing/` stages ERA5 and grid inputs, runs HELP and writes NetCDF. No module of `hydromodpy` outside this folder imports it; the example of `examples/projects/10_coupling_with_land_surface_model_pyhelp/` does.
