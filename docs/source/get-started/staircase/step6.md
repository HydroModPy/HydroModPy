# Step 6: the soil reservoir

```{hmp-task}
Task
: Compute the recharge from the rain and the evapotranspiration instead of reading it, and run the model every day over 2015-2020.

Time
: About 18 min for the run on 2 cores, once the data are cached. The soil check alone takes about 20 s.

Needs
: **Network access** on the first launch, for the SIM2 rain and ETP, then the cache. The example files ({doc}`index`).

Gives
: Eleven figures and six files, with the soil budget in mm/year printed by the check.
```

Step 6 computes the recharge instead of reading it. A daily soil reservoir turns the rain
and the evapotranspiration (ETP) of the SIM2 reanalysis into a recharge that falls to
zero in a dry summer, and MODFLOW builds the slow response of the aquifer itself. The file
explains why: the SIM2 drainage keeps about 0.3 mm/day all summer from 31 July 2015 on, a slow
flow that the aquifer model also computes, so it may be counted twice. The run is daily over
2015-2020. 2015 settles the soil and the aquifer, and the figures score 2016-2020.

```{image} /_static/figures/staircase/step6/flux_timeseries.webp
:alt: Daily water balance of the model over 2015-2020. The recharge comes in bursts in winter and is zero in summer. The drain outflow decays through each summer.
:class: only-light
:width: 90%
:align: center
```

```{image} /_static/figures/staircase/step6/flux_timeseries-dark.webp
:alt: Daily water balance of the model over 2015-2020. The recharge comes in bursts in winter and is zero in summer. The drain outflow decays through each summer.
:class: only-dark
:width: 90%
:align: center
```

## The file

This step inherits `project.toml`, the frozen reference model of the example, and not
step 5. The marks compare it with that file.

::::{tab-set}

:::{tab-item} The file
```{hmp-step} step6_soil_reservoir.toml
```
:::

:::{tab-item} Changed vs project.toml
The resolved file of step 6 against the resolved file of `project.toml`.

```{hmp-toml-diff} project.toml step6_soil_reservoir.toml
```
:::

::::

## Run it

Check the soil alone first. This loads the rain and the ETP, prints the soil budget in
mm/year and the recharge for other soil capacities beside the gauged discharge, and writes
no run, according to the header of the file.

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run step6_soil_reservoir.toml --until load_data
```

Then run the whole model:

```bash
hmp run step6_soil_reservoir.toml
```
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

hmp.run("step6_soil_reservoir.toml", until_step="load_data")  # the soil check, returns None
run = hmp.run("step6_soil_reservoir.toml").open()
```
:::

::::

The check ends with this table:

```text
mm/year                   mean   2016 least rain   2019 most rain
precipitation            911.4             797.3           1032.8
ETP                      692.5             634.9            724.1
ETR                      561.2             522.1            536.9
recharge to MODFLOW      350.1             296.9            495.0
...
unmet ETP 131.3 mm/year, offered to EVT: the water table gives it only where it is shallow
recharge July-September: 0.000 mm/day
recharge for other ru, mm/year: 50 mm 443.0 | 100 mm 388.8 | 150 mm 350.1 | 200 mm 314.5 | 250 mm 280.2
gauged discharge NANCON: 326.5 mm/year on 2192 of 2192 days, catchment 64.62 km2
```

The first launch needs network access for the SIM2 rain and ETP. The downloads are cached.
The run is 2192 daily solves, so it takes longer than the monthly steps. Without a network,
the failure is the one of {doc}`step 3 <step3>`, with the SIM2 source in the message.

## What you get

Ten figures. The one-instant figures draw 15 September 2019, the end of a dry summer,
except the seepage figure, which draws 15 February 2020, near the largest saturated extent.

| Request | What it shows |
|---|---|
| `preset = "watershed_id_card"` | As in step 1 |
| `preset = "water_budget"` | The water balance through time, with the soil recharge and the water table evaporation among the components |
| `preset = "hydrograph"` | Simulated and gauged discharge |
| `preset = "hydrograph"`, `scale = "log"` | The discharge on a log axis, which weighs the recessions. The scored years, 2016 to 2020, are shaded, 2015 being the spin-up |
| `variable = "discharge"`, `type = "distribution"`, `cumulative = true` | The flow-duration curve at the gauge: the share of time each discharge is exceeded |
| `preset = "recession"` | The recession limbs extracted from the discharge series |
| `variable = "watertable_depth"`, `variable = "seepage_mask"`, and a `type = "section"` of `watertable_elevation` | As in step 1, for the dates above |
| `variable = "simulated_active_network"`, `reduce = "frequency"` | The share of the run each cell flows |

Four export blocks write six files in `runs/nancon_soil_reservoir_daily/exports/`: the catchment
and the mapped network (two GeoPackages), the water table and the seepage cells of
15 September 2019 (two GeoTIFFs), the simulated and gauged discharge over the scored years
(CSV), and the daily water budget (CSV).

## Key fields

```{hmp-params}
flow.sinks_sources.recharge.soil.ru
flow.first_period_steady
flow.sinks_sources.etp.extinction_depth
simulation.time.step_value
```

`ru` is what the roots can draw, a property of the site: no value is typical. The file sets
150 mm, inside the 100 to 200 mm that the soil map of Brittany gives on schist and granite.
The value first came from matching the SIM2 drainage plus runoff over 2015-2020, but that
window holds the step of the SIM2 drainage, so the match proves nothing. Its other soil
parameters keep their defaults. The ETP that the soil could not
meet is offered to the water table, which evaporates it where it is shallow: the rate is
full at the drain elevation and falls to zero {toml}`2 m below it|flow.sinks_sources.etp.extinction_depth`.

Previous: {doc}`step5`. To see how the soil reservoir works, read {doc}`../../theory/soil-reservoir`.
K and Sy by zone are keys of {doc}`[flow.param] <../../reference/parameters/flow/param>`.
After the last step: {doc}`next`.
