# model/soil

The daily soil reservoir, a model that makes a recharge from the weather before the groundwater solve.
`config.py` is what `[flow.sinks_sources.recharge.soil]` can say, with each bound and its refusal in two
tables. `kernel.py` is the arithmetic, one function per equation with its reference, and it needs only
numpy. The other modules run the kernel on the loaded precipitation and ETP grids.
`workflow/steps/data.py` calls them when the soil section is set, and gives the recharge to the flow.

## Modules

| module | answers |
|---|---|
| `budget.py` | The printed water-budget block of the soil reservoir |
| `columns.py` | The soil columns: one per SAFRAN cell, or one per capacity class inside each cell |
| `config.py` | What `[flow.sinks_sources.recharge.soil]` can say, with each bound and its refusal |
| `grids.py` | The precipitation and ETP grids the soil reads, and the guards they must pass |
| `kernel.py` | The daily step of the soil reservoir, one function per equation |
| `recharge.py` | Runs the reservoir on the loaded grids and returns recharge, residual ETP and runoff fields |

`grids.py` reads the grids on the days of the run and checks them: daily step, calendar, CRS, no gap, no
negative value, a plausible scale. It never touches the cached dataset of a shared record. `columns.py`
places one column per SAFRAN cell, or one per capacity class inside each cell when `[data.soil_capacity]`
gives a raster, each weighed by its share of the catchment. `recharge.py` runs the reservoir day by day
(`compute_soil_forcings`) and hands back the recharge, the residual ETP and the runoff on the
precipitation grid. `ru_ladder` gives the basin recharge for a few soil capacities. `budget.py` writes the
water-budget block of the run, and the gauged discharge it is compared to.

The loaded records are read through `model/contracts.py`, so nothing here imports `data`. The PyHELP
recharge model (MIT licence) is not here. Nothing in the wheel used it, so it sits in
`hydromodpy_annex/physics/pyhelp/`, and the example `examples/projects/10_coupling_with_land_surface_model_pyhelp/`
runs it from a checkout. The unit tests are in `tests/unit/model/soil/`, and the theory is in
`docs/source/theory/soil-reservoir.md`.
