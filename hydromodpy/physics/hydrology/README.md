# physics/hydrology

The models that make a recharge from the weather, before the groundwater solve.

## Folders

1. `soil_reservoir/` is the daily soil reservoir. `config.py` is what `[flow.sinks_sources.recharge.soil]` can say, with each bound and its refusal in two tables. `kernel.py` is the arithmetic, one function per equation with its reference. `simulation/soil/` runs it on the loaded grids.
2. `synthetic/` makes synthetic precipitation, inflow and recharge series for demonstrators and tests.

The PyHELP recharge model (MIT licence) is not here. Nothing in the wheel used it, so it sits in `hydromodpy_annex/physics/pyhelp/`. The example `examples/projects/10_coupling_with_land_surface_model_pyhelp/` runs it from a checkout.
