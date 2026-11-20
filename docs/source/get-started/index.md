# A first run

Install HydroModPy, run a first model in under a minute, then run example 04 from its file and
from Python.

## Quick start

Six commands. Run them in a terminal where Python 3.11 to 3.13 is available, and in a
virtual environment if you keep one ({doc}`install` has the variants for Windows and conda).

```bash
pip install hydromodpy
hmp workspace init
cd ~/hydromodpy
hmp run projects/example/run_demo.toml
hmp example add 04
hmp run projects/04_streamflow_intermittence_in_transient/project.toml
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
| `hmp run projects/04_.../project.toml` | Solves the real catchment month by month from 2000 to 2002 with MODFLOW 6, draws eight figures and writes four groups of files. | about 1.5 min |

The clock on the last line of a run, `Run completed`, is shorter than what you wait: Python
starts, imports the geospatial stack and reads the configuration first. Count 15 to 30 s
more than the figure. The numbers above are measured, on a machine that was sometimes busy
with other work.

A run ends with this, the name and the first eight characters of the run id being yours:

```text
Run completed: nancon_intermittence_mf6 [b9716f06] 86s nse=0.97
next: hmp show nancon_intermittence_mf6 | hmp publish nancon_intermittence_mf6 --to <folder> | hmp export nancon_intermittence_mf6 --list
```

The figures of that run are in `runs/nancon_intermittence_mf6/figures/`, among them the depth of
the water table in October 2002 with the cells where it reaches the ground. The run prints one
`WARNING` line on the way, about the outlet. {doc}`example-04` says what it means.

## Then

{doc}`concepts` gives the six words that name the things on disk, in two minutes. Then
{doc}`example-04` walks through the file of example 04 and the script that plays it step by step.
{doc}`install` has the variants of the installation and what to do when it fails.

Looking for one parameter? Go to the {doc}`reference <../reference/parameters/index>`.
