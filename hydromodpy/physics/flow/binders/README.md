# physics/flow/binders

What the data step puts on a built `Flow`. `workflow/steps/data.py` calls these functions in turn, after the data are loaded, and the same cascade runs for a calibration trial. Each `apply_*_to_flow` function returns or leaves the `Flow` ready for the solver, and refuses a value it cannot place.

## Modules

1. `climate.py` puts the sea level on the ocean boundary, and the recharge and ETP on the flow (`apply_oceanic_to_flow`, `apply_recharge_load_result_to_flow`, `apply_etp_load_result_to_flow`). `watershed_mean_rates` is the catchment mean of a loaded series, which the lakes and streams also read.
2. `barriers.py` reads a barrier trace, inline or from a file, and puts the flow barriers on the flow.
3. `streams.py` puts the SFR reach networks on the flow and routes the catchment runoff to them.
4. `lakes.py` puts on each lake its geometry, abacus, bathymetry, cutoff wall, inflow and withdrawal, and its meteo forcings.
5. `payloads.py` turns the lake or SFR table of a `Flow` into plain dicts the binders can enrich.

Lakes read streams (a runoff routed by an active SFR is not given to a lake twice), barriers (the wall trace) and climate. Nothing here imports `data`: a loaded record is read through `physics.contracts.LoadResultProto`.
