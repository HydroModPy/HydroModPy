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
:alt: Map of the catchment over the year 2002. Perennial cells are blue, intermittent cells are orange, dry cells are gray.
:class: only-light
:width: 60%
:align: center
```

```{image} /_static/figures/staircase/step4/flow_intermittence_map-dark.webp
:alt: Map of the catchment over the year 2002. Perennial cells are blue, intermittent cells are orange, dry cells are gray.
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

```{hmp-toml-diff} step2_local_data.toml step4_transient.toml
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

run = hmp.run("step4_transient.toml").open()
```

This is also what `py1_run_and_plot.py` of the example does, before it draws its own
figure. {doc}`next` lists the scripts.
:::

::::

Two points of the file are worth a second look. {toml}`flow.flow_regime` is written again,
because an inherited `"steady"` is not undone by the default. {toml}`data.types` is written
in full, because a list replaces the parent's.

## What you get

Four figures. The seepage figure writes its instant in {toml}`display.figure.time`, here
15 October 2002, the driest month according to the file.

| Request | What it shows |
|---|---|
| `preset = "water_budget"` | The components of the water balance through time, inflows positive and outflows negative |
| `preset = "hydrograph"` | The simulated discharge against the gauged one |
| `variable = "seepage_mask"`, `time = "2002-10-15"` | The seepage cells of October 2002 |
| `variable = "simulated_active_network"`, `reduce = "frequency"` | The share of the three years each cell flows: dark where the channel ran all year, pale where it ran only at the wettest steps |

Six export blocks write seven files in `runs/nancon_step4_transient/exports/`: the five files of
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
display.figure.time
```

The time step is not written: {toml}`simulation.time.step_value` defaults to {default}`simulation.time.step_value`.

Next: {doc}`step5`, which writes the results in every format.
