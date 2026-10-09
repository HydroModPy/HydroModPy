# Get started

Install HydroModPy, run a first model in under a minute, then climb example 04 in six
files. The first file of the staircase is the shortest configuration that solves. The last
one computes the recharge from a soil reservoir.

## Quick start

Five commands. Run them in a terminal where Python 3.11 to 3.13 is available, and in a
virtual environment if you keep one ({doc}`install` has the variants for Windows and conda).

```bash
pip install --pre hydromodpy
hmp workspace init
hmp run ~/hydromodpy/projects/example/run_demo.toml
hmp example add 04
hmp run ~/hydromodpy/projects/04_streamflow_intermittence_in_transient/step1_minimal.toml
```

What each command does, and how long it took on a clean machine (a 2-core laptop, fast
connection):

| Command | What it does | Time |
|---|---|---|
| `pip install --pre hydromodpy` | Installs the package and its geospatial wheels, 1.3 GB in a clean environment. | about 2 min |
| `hmp workspace init` | Makes `~/hydromodpy`, with 27 data folders and the project `example`. | 8 s |
| `hmp run .../run_demo.toml` | Solves a synthetic 1 km square with MODFLOW-NWT. No download, except the solver itself the very first time. | 9 to 15 s |
| `hmp example add 04` | Fetches the Nançon catchment, 92 MiB, most of it a regional DEM. Cached by content: a second workspace costs nothing. | 20 s |
| `hmp run .../step1_minimal.toml` | Solves the real catchment in steady state with MODFLOW 6, draws five figures and writes four files. | 25 to 45 s |

The clock on the last line of a run, `Run completed`, is shorter than what you wait: Python
starts, imports the geospatial stack and reads the configuration first. Count 15 to 30 s
more than the figure. The numbers above are measured, on a machine that was sometimes busy
with other work.

A run ends with this, the name and the first eight characters of the run id being yours:

```text
Run completed: nancon_step1_minimal [3fd2f8e3] 19s
next: hmp catalog show nancon_step1_minimal | hmp catalog diff nancon_step1_minimal <other> | hmp export nancon_step1_minimal --list
```

The figure of that run is `watertable_depth_map`, in `runs/nancon_step1_minimal/figures/`:
the depth of the water table below the land surface, from 0 m (dark) to 30 m, which is the
thickness of the model.

```{image} /_static/figures/staircase/step1/watertable_depth_map.webp
:alt: Map of the depth to the water table in the Nançon catchment, from 0 to 30 m. The water table is shallow in the valleys and deep on the ridges.
:class: only-light
:width: 70%
:align: center
```

```{image} /_static/figures/staircase/step1/watertable_depth_map-dark.webp
:alt: Map of the depth to the water table in the Nançon catchment, from 0 to 30 m. The water table is shallow in the valleys and deep on the ridges.
:class: only-dark
:width: 70%
:align: center
```

You see `WARNING` lines on the way. They are expected, and
{doc}`step 1 <staircase/step1>` says what each one means.

## Then

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} 1. Install
:link: install
:link-type: doc

2 to 5 minutes. Tabs for Linux, macOS, Windows and conda, the solver binaries, the
platforms tested, and what to do when it fails.
:::

:::{grid-item-card} 2. Concepts
:link: concepts
:link-type: doc

2 minutes. Workspace, project, run, catalog: four words, one folder tree.
:::

:::{grid-item-card} 3. The staircase
:link: staircase/index
:link-type: doc

From 15 s to 20 min per step. Six files of example 04. Each page: what the step adds, how to
run it, what you get.
:::

::::

When the staircase is done, {doc}`staircase/next` leads to your own catchment, to the
calibration files of example 04 and to the Python API.

Already know what you want to do? Go to the {doc}`guides <../guides/index>`. Looking for
one parameter? Go to the {doc}`reference <../reference/parameters/index>`.

```{toctree}
:hidden:

Install <install>
Concepts <concepts>
The staircase <staircase/index>
After the staircase <staircase/next>
```
