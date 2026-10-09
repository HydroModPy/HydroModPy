# Step 4: the transient run

```{hmp-task}
Task
: Run the model month by month over 2000-2002 and see which cells flow, and for how long.

Time
: 1 to 2 min for the run, 1.5 to 3 min for the command.

Needs
: The example files ({doc}`index`), which hold the observed recharge and runoff. Nothing is downloaded.

Gives
: Five figures and seven files, among them a NetCDF of the water table and a CSV of the discharge.
```

Step 4 turns step 2 into a monthly transient run over 2000-2002. The recharge and the
runoff are no longer one mean: 36 monthly values replace the steady rate. The first period
is solved steady and gives the initial heads. K, Sy and Ss are assumed here, not
calibrated. The question changes from where the water table reaches the surface to which
cells flow, and for how long. The baseflow warning of steps 1 and 2 is gone: the runoff is
loaded and added to the discharge.

```{image} /_static/figures/staircase/step4/flow_intermittence_map.webp
:alt: Map of the catchment over the year 2002. Perennial cells are blue, intermittent cells are orange, dry cells are grey.
:class: only-light
:width: 60%
:align: center
```

```{image} /_static/figures/staircase/step4/flow_intermittence_map-dark.webp
:alt: Map of the catchment over the year 2002. Perennial cells are blue, intermittent cells are orange, dry cells are grey.
:class: only-dark
:width: 60%
:align: center
```

## The file

::::{tab-set}

:::{tab-item} The file
```{hmp-step} step4_transient.toml
```
:::

:::{tab-item} Changed vs step 2
The resolved file of step 4 against the resolved file of step 2 (step 4 inherits step 2, not
step 3).

```diff
--- step2_local_data
+++ step4_transient
@@ -7,3 +7,3 @@
 [simulation]
-name = "nancon_step2_local"
+name = "nancon_step4_transient"
 
@@ -21,2 +21,6 @@
 spatial_fields = true
+
+[simulation.time]
+start_datetime = "2000-01-01"
+end_datetime = "2002-12-31"
 
@@ -38,3 +42,3 @@
 [flow]
-flow_regime = "steady"
+flow_regime = "transient"
 param_list = [
@@ -42,2 +46,3 @@
     "Sy",
+    "Ss",
 ]
@@ -60,2 +65,7 @@
 
+[flow.param.Ss.field]
+kind = "homogeneous"
+unit = "m-1"
+value = 1e-05
+
 [flow.sinks_sources.recharge]
@@ -66,7 +76,9 @@
 figures = [
-    "watershed_id_card",
-    "hydrographic_network_reference",
-    "seepage_network_confusion_map",
-    "downslope_distance_map",
+    "flux_timeseries",
+    "hydrograph_sim_obs",
+    "seepage_map",
+    "flow_persistence_map",
+    "flow_intermittence_map",
 ]
+time = "2002-10-15"
 
@@ -74,2 +86,5 @@
 orientation = "sn"
+
+[display.overrides.flow_intermittence_map]
+cycle = "2002"
 
@@ -91,2 +106,14 @@
 
+[[export]]
+variables = [
+    "head",
+    "watertable_depth",
+]
+
+[[export]]
+variables = [
+    "discharge",
+    "discharge_obs",
+]
+
 [data]
@@ -95,2 +122,4 @@
     "hydrometry",
+    "recharge",
+    "runoff",
 ]
@@ -108 +137,15 @@
 ]
+
+[[data.recharge.sources]]
+source = "custom"
+path = "recharge"
+station_ids = [
+    "NANCON",
+]
+
+[[data.runoff.sources]]
+source = "custom"
+path = "runoff"
+station_ids = [
+    "NANCON",
+]
```
:::

::::

## Run it

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run step4_transient.toml
```
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("step4_transient.toml")
```

This is also what `py1_run_and_plot.py` of the example does, before it draws its own
figure. {doc}`next` lists the scripts.
:::

::::

Two points of the file are worth a second look. {toml}`flow.flow_regime` is written again,
because an inherited `"steady"` is not undone by the default. {toml}`data.types` is written
in full, because a list replaces the parent's.

## What you get

Five figures. The instant of the one-instant figures comes from {toml}`display.time`, here
15 October 2002, the driest month according to the file.

| Figure | What it shows |
|---|---|
| `flux_timeseries` | The components of the water balance through time, inflows positive and outflows negative |
| `hydrograph_sim_obs` | The simulated discharge against the gauged one |
| `seepage_map` | The seepage cells of October 2002 |
| `flow_persistence_map` | The share of the three years each cell flows: dark where the channel ran all year, pale where it ran only at the wettest steps |
| `flow_intermittence_map` | One calendar year, 2002 (`cycle = "2002"`): each cell is perennial, intermittent or dry |

Six export blocks write seven files in `share/nancon_step4_transient/`: the five files of
the inherited blocks, now of a transient run (the GeoTIFFs hold December 2002, the last
month), and two more.

| Block | File |
|---|---|
| `["head", "watertable_depth"]` | the water table over the 36 months, one NetCDF file |
| `["discharge", "discharge_obs"]` | simulated and gauged discharge, a CSV: the model monthly, the gauge daily |

## Key fields

```{hmp-params}
simulation.time.start_datetime
simulation.time.end_datetime
flow.param.Ss.field.value
display.time
```

The time step is not written: {toml}`simulation.time.step_value` defaults to one month.

Next: {doc}`step5`, which writes the results in every format.
