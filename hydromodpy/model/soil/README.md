# model/soil

The daily soil reservoir, a model that makes a recharge from the weather before the groundwater solve.
This folder holds the arithmetic only. `kernel.py` is one function per equation with its reference, and it
needs only numpy. It follows rule 6, so it reads from top to bottom and imports no neighbour.

## Modules

| module | answers |
|---|---|
| `kernel.py` | The daily step of the soil reservoir, one function per equation |

The TOML surface and the run on the loaded grids sit in `model/forcing/`, because they read the records
that a project loads. `soil_config.py` is what `[flow.sinks_sources.recharge.soil]` can say, with each
bound and its refusal in two tables. `soil_grids.py` reads the precipitation and ETP grids on the days of
the run and checks them. `soil_columns.py` places one column per SAFRAN cell, or one per capacity class
inside each cell. `soil_forcing.py` runs the kernel day by day (`compute_soil_forcings`) and hands back the
recharge, the residual ETP and the runoff. `soil_budget.py` writes the water-budget block of the run.
`workflow/steps/data.py` calls them when the soil section is set, and gives the recharge to the flow.

The PyHELP recharge model (MIT licence) is not here. Nothing in the wheel used it, so it sits in
`hydromodpy_annex/physics/pyhelp/`, and the example `examples/projects/10_coupling_with_land_surface_model_pyhelp/`
runs it from a checkout. The unit test of the kernel is `tests/unit/model/soil/test_soil_kernel.py`, and the
theory is in `docs/source/theory/soil-reservoir.md`.
