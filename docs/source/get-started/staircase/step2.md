# Step 2: the mapped network and the gauge

```{hmp-task}
Task
: Compare the cells where the simulated water table reaches the surface with the mapped river network and the gauge.

Time
: 15 to 25 s for the run, 40 to 60 s for the command.

Needs
: The example files ({doc}`index`). Nothing is downloaded.

Gives
: Four figures and five files, with the mapped network among them.
```

Step 2 adds two pieces of data, read from local files: the mapped stream network and the
discharge gauge at the outlet. The run is still steady. The point is the comparison: the
cells where the simulated water table reaches the surface should lie where the map draws a
stream. The figures show where they agree and how far each simulated cell is from the map.

```{image} /_static/figures/staircase/step2/seepage_network_confusion_map.webp
:alt: Map of the catchment. Cells where the simulation and the map both have a stream are dark blue, cells where only the model has one are yellow, cells where only the map has one are red.
:class: only-light
:width: 60%
:align: center
```

```{image} /_static/figures/staircase/step2/seepage_network_confusion_map-dark.webp
:alt: Map of the catchment. Cells where the simulation and the map both have a stream are dark blue, cells where only the model has one are yellow, cells where only the map has one are red.
:class: only-dark
:width: 60%
:align: center
```

## The file

::::{tab-set}

:::{tab-item} The file
```{hmp-step} step2_local_data.toml
```
:::

:::{tab-item} Changed vs step 1
The resolved file of step 2 against the resolved file of step 1: `-` is what step 1 has,
`+` is what step 2 has. The name changes too.

```{hmp-toml-diff} step1_minimal.toml step2_local_data.toml
```
:::

::::

## Run it

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run step2_local_data.toml
```
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("step2_local_data.toml")
```
:::

::::

The network is the GeoPackage `nancon_stream_network.gpkg`, which `hmp example add` put in
`data/hydrography/`. The gauge is the `NANCON` station of `data/hydrometry/`, a daily record
from 1982 to 2022. Nothing is downloaded. The run prints the same first two warnings as
step 1: {ref}`they are explained there <staircase-warnings>`.

## What you get

{toml}`display.figures` is a list, so step 2 replaces step 1's list. Four figures:

| Figure | What it shows |
|---|---|
| `watershed_id_card` | As in step 1 |
| `hydrographic_network_reference` | The mapped network alone |
| `seepage_network_confusion_map` | Three classes: *valid* where the two networks share a cell, *excess* where only the model has a stream, *missing* where only the map has one |
| `downslope_distance_map` | How far each simulated cell must descend before it reaches the mapped network, in four classes: 0 to 75 m, 75 to 500 m, 500 to 1000 m, and more than 1000 m |

Step 1's three exports are inherited. `[[export__append]]` adds a fourth block: the mapped
network, as a GeoPackage. Five files land in `share/nancon_step2_local/`.

## Key fields

```{hmp-params}
data.types
data.hydrography.sources.path
```

Next: {doc}`step3`, the same data from the APIs, or {doc}`step4`, the transient run.
