# Step 6: the soil reservoir

Step 6 computes the recharge instead of reading it. A daily soil reservoir turns the rain
and the evapotranspiration (ETP) of the SIM2 reanalysis into a recharge that falls to
zero in a dry summer, and MODFLOW builds the slow response of the aquifer itself. The file
explains why: the SIM2 drainage keeps about 0.3 mm/day all summer from 2016 on, a slow
groundwater memory that the aquifer model would then count twice. The run is daily over
2015-2020. 2015 settles the soil and the aquifer, and the figures score 2016-2020.

## The file

This step inherits `project.toml`, the frozen reference model of the example, and not
step 5. The marks compare it with that file.

```{hmp-step} step6_soil_reservoir.toml
```

## Run it

Check the soil alone first. This loads the rain and the ETP, prints the soil budget in
mm/year and the recharge for other soil capacities beside the gauged discharge, and writes no
run, according to the header of the file:

```bash
hmp run step6_soil_reservoir.toml --until load_data
```

Then run the whole model:

```bash
hmp run step6_soil_reservoir.toml
```

The first launch needs network access for the SIM2 rain and ETP. The downloads are cached.
The run is 2192 daily solves, so it takes longer than the monthly steps.

## What you get

Eleven figures. The one-instant figures draw 15 September 2019, the end of a dry summer,
except `seepage_map`, which draws 15 February 2020, near the largest saturated extent.

| Figure | What it shows |
|---|---|
| `watershed_id_card` | As in step 1 |
| `flux_timeseries` | The water balance through time, with the soil recharge and the water table evaporation among the components |
| `hydrograph_sim_obs` | Simulated and gauged discharge |
| `hydrograph_log_nse` | The discharge on a log axis, which weighs the recessions. The scored years, 2016 to 2020, are shaded, 2015 being the spin-up |
| `duration_curve` | The flow-duration curve at the gauge: the share of time each discharge is exceeded |
| `recession` | The recession limbs extracted from the discharge series |
| `watertable_depth_map`, `seepage_map`, `cross_section` | As in step 1, for the dates above |
| `flow_persistence_map` | The share of the run each cell flows |
| `flow_intermittence_map` | Perennial, intermittent or dry cells over the hydrological year 2019 |

Four exports in `share/nancon_soil_reservoir_daily/`: the catchment and the mapped network
(GeoPackage), the water table and the seepage cells of 15 September 2019 (GeoTIFF), the
simulated and gauged discharge over the scored years (CSV), and the daily water budget
(CSV).

## Key fields

```{hmp-params}
flow.sinks_sources.recharge.soil.ru
flow.first_period_steady
flow.sinks_sources.etp.extinction_depth
simulation.time.step_value
```

`ru` is what the roots can draw, a property of the site: no value is typical. The file sets
150 mm and notes that the recharge of 2015-2020 then matches the SIM2 drainage plus
runoff. Its other soil parameters keep their defaults. The ETP that the soil could not
meet is offered to the water table, which evaporates it where it is shallow: the rate is
full at the drain elevation and falls to zero {toml}`1 m below it|flow.sinks_sources.etp.extinction_depth`.

Previous: {doc}`step5`. To see how the soil reservoir works, read {doc}`../../theory/soil-reservoir`.
For K and Sy by zone and the recharge choice, see the {doc}`guides <../../guides/index>`.
