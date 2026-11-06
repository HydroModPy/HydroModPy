# simulation/soil

The soil reservoir of `physics/hydrology/soil_reservoir/` run on the loaded precipitation and ETP grids. `workflow/steps/data.py` calls it when `[flow.sinks_sources.recharge.soil]` is set, and gives its recharge to the flow.

## Modules, in the order of a run

1. `grids.py` reads the precipitation and ETP grids on the days of the run and checks them: daily step, calendar, CRS, no gap, no negative value, a plausible scale. It never touches the cached dataset of a shared record.
2. `columns.py` places the soil columns: one per SAFRAN cell, or one per capacity class inside each cell when `[data.soil_capacity]` gives a raster, each weighed by its share of the catchment.
3. `recharge.py` runs the reservoir day by day (`compute_soil_forcings`) and hands back the recharge, residual ETP and runoff on the precipitation grid. `ru_ladder` gives the basin recharge for a few soil capacities.
4. `budget.py` writes the printed water-budget block of the run, and the gauged discharge it is compared to.

The loaded records are read through `physics.contracts`, so nothing here imports `data`. A new record is built from the precipitation record it follows.
