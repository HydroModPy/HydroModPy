# The staircase

Example 04 models the Nançon catchment (Ille-et-Vilaine) with MODFLOW 6. It ships as a
staircase of six TOML files. Each file inherits another one and writes only what it
changes, so the page of a step shows you only what that step adds.

| Step | File | What it adds | Inherits | Needs | Time |
|---|---|---|---|---|---|
| {doc}`1 <step1>` | `step1_minimal.toml` | The shortest file that runs: steady state, local DEM, one K, one recharge rate | nothing | the example files | 15 to 25 s |
| {doc}`2 <step2>` | `step2_local_data.toml` | The mapped stream network and the gauge, from local files, compared with the simulated seepage | step 1 | the example files | 15 to 25 s |
| {doc}`3 <step3>` | `step3_api_data.toml` | The same data, fetched from the BD Topage and Hub'Eau APIs | step 2 | **network**, first run | about 40 s |
| {doc}`4 <step4>` | `step4_transient.toml` | Monthly transient run, 2000-2002, forced by observed recharge and runoff | step 2 | the example files | 1 to 2 min |
| {doc}`5 <step5>` | `step5_export.toml` | The results written out in every format | step 4 | the example files | 1 to 2 min |
| {doc}`6 <step6>` | `step6_soil_reservoir.toml` | Daily run, 2015-2020, recharge computed by a soil reservoir | `project.toml` | **network**, first run | about 18 min |

Steps 1, 2, 4 and 5 run offline once the example is added. Steps 3 and 6 read APIs on their
first run and use the cache after that. The times are the `Run completed` figure of the
last line, measured on 2 cores; the command takes 15 to 30 s longer, because Python
starts and imports first.

Step 3 is a variant of step 2, not a rung above it. Step 6 starts again from
`project.toml`, the frozen reference model of the example.

```text
step 1 ── step 2 ─┬─ step 3   same data, from APIs
                  └─ step 4 ── step 5
project.toml ── step 6
```

## What each step shows

One figure of each step, the one that carries its idea. Each page shows the others.

::::{grid} 1 2 3 3
:gutter: 3

:::{grid-item-card} 1. Water-table depth
:link: step1
:link-type: doc

```{image} /_static/figures/staircase/step1/watertable_depth_map.webp
:alt: Depth to the water table over the Nançon catchment, steady state.
:class: only-light
```

```{image} /_static/figures/staircase/step1/watertable_depth_map-dark.webp
:alt: Depth to the water table over the Nançon catchment, steady state.
:class: only-dark
```
:::

:::{grid-item-card} 2. Model against map
:link: step2
:link-type: doc

```{image} /_static/figures/staircase/step2/seepage_network_confusion_map.webp
:alt: Cells where the simulated seepage and the mapped network agree, or where only one of them has a stream.
:class: only-light
```

```{image} /_static/figures/staircase/step2/seepage_network_confusion_map-dark.webp
:alt: Cells where the simulated seepage and the mapped network agree, or where only one of them has a stream.
:class: only-dark
```
:::

:::{grid-item-card} 3. Permanent reaches
:link: step3
:link-type: doc

```{image} /_static/figures/staircase/step3/hydrographic_network_permanence.webp
:alt: The BD Topage network, all reaches and the reaches that flow all year.
:class: only-light
```

```{image} /_static/figures/staircase/step3/hydrographic_network_permanence-dark.webp
:alt: The BD Topage network, all reaches and the reaches that flow all year.
:class: only-dark
```
:::

:::{grid-item-card} 4. Flow intermittence
:link: step4
:link-type: doc

```{image} /_static/figures/staircase/step4/flow_intermittence_map.webp
:alt: Perennial, intermittent and dry cells over the year 2002.
:class: only-light
```

```{image} /_static/figures/staircase/step4/flow_intermittence_map-dark.webp
:alt: Perennial, intermittent and dry cells over the year 2002.
:class: only-dark
```
:::

:::{grid-item-card} 5. Water-table depth on 15 October 2002
:link: step5
:link-type: doc

```{image} /_static/figures/staircase/step5/watertable_depth_map.webp
:alt: Depth to the water table on 15 October 2002.
:class: only-light
```

```{image} /_static/figures/staircase/step5/watertable_depth_map-dark.webp
:alt: Depth to the water table on 15 October 2002.
:class: only-dark
```
:::

:::{grid-item-card} 6. Water balance through time
:link: step6
:link-type: doc

```{image} /_static/figures/staircase/step6/flux_timeseries.webp
:alt: Daily water balance of the run, with the soil recharge among the components.
:class: only-light
```

```{image} /_static/figures/staircase/step6/flux_timeseries-dark.webp
:alt: Daily water balance of the run, with the soil recharge among the components.
:class: only-dark
```
:::

::::

The images come from real runs of these files. The command that made each one is in
`tools/docs/figures/figures.toml`.

## Get the example once

```bash
hmp workspace init ~/hydromodpy
hmp example add 04 -w ~/hydromodpy
cd ~/hydromodpy/projects/04_streamflow_intermittence_in_transient
```

`hmp example add` downloads the files of the example, 92 MiB, most of it a regional DEM of
90 MiB. Files are cached by content, so a second workspace costs nothing. `hmp example list`
shows the examples your version ships and `hmp example show 04` lists the files one by one.

## Run a step

Run any step from that folder. Each run writes its figures to `runs/<name>/figures/` and
its exports to `share/<name>/`, where `<name>` is the {toml}`simulation.name` of the file.

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run step1_minimal.toml
```
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("step1_minimal.toml")
print(run.name)
```

A relative path is read from the folder you are in. `hmp.run` returns the
{doc}`Run <../../reference/python/Run>`, whose reference page lists what it reads.
:::

::::

(staircase-rerun)=
## Run a step twice

Run an unchanged file a second time and nothing is computed. The command prints two lines
on the error stream and exits with code 0:

```text
Config identical to completed run 'nancon_step1_minimal' [3fd2f8e3]; nothing to do.
Re-run with --force to run it again.
```

`hmp run --force` computes it again. In Python, `hmp.run(path)` returns the existing `Run`
and logs a warning, and `hmp.run(path, force=True)` computes it again.

Edit the file, even one value, and the second run is a new one. It lands next to the first,
as `runs/nancon_step1_minimal.v2/`, then `.v3`, because {toml}`simulation.if_exists` is
`"version"` by default. Set it to `"replace"` and the older run goes to the trash instead.
{doc}`hmp catalog <../../reference/cli/catalog>` lists, compares and deletes them.

```{toctree}
:hidden:

Step 1: minimal <step1>
Step 2: local data <step2>
Step 3: API data <step3>
Step 4: transient <step4>
Step 5: export <step5>
Step 6: soil reservoir <step6>
```
