# physics/forcing

How a loaded series becomes the value a solver reads.

## Modules, in the order a forcing goes through them

1. `forcing_bridge.py` turns a loaded record into a forcing: `resolve_forcing` takes a homogeneous series or a gridded field and returns the series the flow keeps.
2. `time_alignment.py` gives a series one value per stress period of `[simulation.time]` (`align_forcing_series_to_simulation_window`): the mean of the samples of each period, each monthly or yearly sample weighed by its length.
3. `steady_periods.py` is the rule every solver shares for a steady period: which periods are steady, and the rate a steady period takes (`first_clim`, `normalize_first_clim`).
4. `validation.py` holds the numeric checks of a forcing payload, and refuses a recharge beyond any daily rain.
5. `types.py` holds three small aliases: the spatial mode, the `first_clim` keyword and the interpolation method.
