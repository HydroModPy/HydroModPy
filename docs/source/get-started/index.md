# A first run

Install HydroModPy, run a first model in under a minute, then climb example 04 in six
files. The first file of the staircase is the shortest configuration that solves. The last
one computes the recharge from a soil reservoir.

## Quick start

Six commands. Run them in a terminal where Python 3.11 to 3.13 is available, and in a
virtual environment if you keep one ({doc}`install` has the variants for Windows and conda).

```bash
pip install hydromodpy
hmp workspace init
cd ~/hydromodpy
hmp run projects/example/run_demo.toml
hmp example add 04
hmp run projects/04_streamflow_intermittence_in_transient/step1_minimal.toml
```

What each command does, and how long it took on a clean machine (a 2-core laptop, fast
connection):

| Command | What it does | Time |
|---|---|---|
| `pip install hydromodpy` | Installs the package and its geospatial wheels, 1.3 GB in a clean environment. | about 2 min |
| `hmp workspace init` | Makes `~/hydromodpy`, with 27 data folders and the project `example`. | 8 s |
| `cd ~/hydromodpy` | Enters the workspace. `hmp example add` looks for a workspace at or above the current folder and has no default. Elsewhere, add `-w ~/hydromodpy`. | instant |
| `hmp run projects/example/run_demo.toml` | Solves a synthetic 1 km square under a steady recharge with MODFLOW-NWT. No download, except the solver itself the very first time. | 9 to 15 s |
| `hmp example add 04` | Fetches the Nançon catchment, 92 MiB, most of it a regional DEM. Cached by content: a second workspace costs nothing. | 20 s |
| `hmp run projects/04_.../step1_minimal.toml` | Solves the real catchment in steady state with MODFLOW 6, draws five figures and writes four files. | 25 to 45 s |

The clock on the last line of a run, `Run completed`, is shorter than what you wait: Python
starts, imports the geospatial stack and reads the configuration first. Count 15 to 30 s
more than the figure. The numbers above are measured, on a machine that was sometimes busy
with other work.

A run ends with this, the name and the first eight characters of the run id being yours:

```text
Run completed: nancon_step1_minimal [3fd2f8e3] 19s
next: hmp show nancon_step1_minimal | hmp publish nancon_step1_minimal --to <folder> | hmp export nancon_step1_minimal --list
```

The figure of that run is the map of the variable `watertable_depth`, in `runs/nancon_step1_minimal/figures/`:
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

{doc}`concepts` gives the six words that name the things on disk, in two minutes. Then
{doc}`the staircase <staircase/index>` climbs example 04 in six files, from 15 s to 20 min
per step. {doc}`install` has the variants of the installation and what to do when it fails.

Looking for one parameter? Go to the {doc}`reference <../reference/parameters/index>`.
