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
explains why: the SIM2 drainage keeps about 0.3 mm/day all summer from 2016 on, a slow
groundwater memory that the aquifer model would then count twice. The run is daily over
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

```diff
--- project
+++ step6_soil_reservoir
@@ -7,4 +7,4 @@
 [simulation]
-name = "nancon_intermittence_mf6"
-description = "Nancon catchment, monthly transient 2000-2002, seasonal seepage intermittence."
+name = "nancon_soil_reservoir_daily"
+description = "Nancon, daily 2015-2020, recharge from a soil reservoir on the SIM2 rain and ETP."
 if_exists = "replace"
@@ -12,5 +12,5 @@
 [simulation.time]
-start_datetime = "2000-01-01"
-end_datetime = "2002-12-31"
-step_value = "1 month"
+start_datetime = "2015-01-01"
+end_datetime = "2020-12-31"
+step_value = "1 day"
 
@@ -49,4 +49,4 @@
     "hydrometry",
-    "recharge",
-    "runoff",
+    "precipitation",
+    "etp",
 ]
@@ -70,14 +70,10 @@
 
-[[data.recharge.sources]]
-source = "custom"
-path = "recharge"
-station_ids = [
-    "NANCON",
+[data.precipitation]
+sources = [
+    { source = "sim2", extent = "watershed" },
 ]
 
-[[data.runoff.sources]]
-source = "custom"
-path = "runoff"
-station_ids = [
-    "NANCON",
+[data.etp]
+sources = [
+    { source = "sim2", extent = "watershed" },
 ]
@@ -92,2 +88,3 @@
     "recharge",
+    "etp",
 ]
@@ -96,2 +93,3 @@
 ]
+first_period_steady = false
 
@@ -112,5 +110,11 @@
 
+[flow.ic]
+type = "steady_state"
+
+[flow.sinks_sources.recharge.soil]
+ru = "150 mm"
+
 [display]
-on_error = "raise"
-time = "2002-10-15"
+on_error = "warn"
+time = "2019-09-15"
 figures = [
@@ -119,14 +123,10 @@
     "hydrograph_log_nse",
-    "cross_section",
+    "hydrograph_sim_obs",
+    "duration_curve",
+    "recession",
     "watertable_depth_map",
     "seepage_map",
+    "cross_section",
     "flow_persistence_map",
     "flow_intermittence_map",
-    "seepage_network_confusion_map",
-    "downslope_distance_map",
-    "downslope_distance_crossing",
-    "bisection_bracket_trace",
-    "parameter_cost_profile",
-    "matching_hydrographic_network_card",
-    "calibration_progress",
 ]
@@ -137,3 +137,3 @@
 [display.overrides.flow_intermittence_map]
-cycle = "2002"
+cycle = "2019"
 
@@ -141,5 +141,8 @@
 scoring_window = [
-    "2001-01-01",
-    "2002-12-31",
+    "2016-01-01",
+    "2020-12-31",
 ]
+
+[display.overrides.seepage_map]
+time = "2020-02-15"
 
@@ -156,3 +159,3 @@
 ]
-time = "2002-10-15"
+time = "2019-09-15"
 
@@ -163,2 +166,6 @@
 ]
+period = [
+    "2016-01-01",
+    "2020-12-31",
+]
 
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
run = hmp.run("step6_soil_reservoir.toml")
```
:::

::::

The check ends with this table:

```text
mm/year                   mean   2016 least rain   2019 most rain
precipitation            903.9             790.4           1024.8
ETP                      698.3             640.7            729.8
ETR                      547.4             512.0            526.0
recharge to MODFLOW      356.4             291.1            497.8
...
unmet ETP 150.8 mm/year, offered to EVT: the water table gives it only where it is shallow
recharge July-September: 0.004 mm/day
recharge for other ru, mm/year: 50 mm 442.8 | 100 mm 392.4 | 150 mm 356.4 | 200 mm 324.8 | 250 mm 295.2
gauged discharge NANCON: 326.5 mm/year on 2192 of 2192 days, catchment 64.62 km2
```

The first launch needs network access for the SIM2 rain and ETP. The downloads are cached.
The run is 2192 daily solves, so it takes longer than the monthly steps. Without a network,
the failure is the one of {doc}`step 3 <step3>`, with the SIM2 source in the message.

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

Four export blocks write six files in `share/nancon_soil_reservoir_daily/`: the catchment
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
150 mm and notes that the recharge of 2015-2020 then matches the SIM2 drainage plus
runoff. Its other soil parameters keep their defaults. The ETP that the soil could not
meet is offered to the water table, which evaporates it where it is shallow: the rate is
full at the drain elevation and falls to zero {toml}`1 m below it|flow.sinks_sources.etp.extinction_depth`.

Previous: {doc}`step5`. To see how the soil reservoir works, read {doc}`../../theory/soil-reservoir`.
For K and Sy by zone and the recharge choice, see the {doc}`guides <../../guides/index>`.
After the last step: {doc}`next`.
