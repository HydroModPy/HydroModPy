# Example 04

Example 04 models the Nançon catchment (Ille-et-Vilaine) with MODFLOW 6, from 2000
to 2002 in monthly stress periods. As the recharge swings between wet winters and dry summers,
the cells where the water table reaches the ground spread out and draw back. The example is two
files. `project.toml` says the model, its figures and its exports, and `hmp run` plays it in
about a minute and a half. `py1_run_and_plot.py` plays the same file one step at a time from
Python, looks at what each step built, and tries three values of Sy.

## Get the example

```bash
hmp workspace init ~/hydromodpy
hmp example add 04 -w ~/hydromodpy
cd ~/hydromodpy/projects/04_streamflow_intermittence_in_transient
```

`hmp example add` downloads the files of the example, about 92 MiB, most of it a regional DEM.
Files are cached by content, so a second workspace costs nothing. `hmp example list` shows the
examples your version ships and `hmp example show 04` lists the files one by one.
`hmp example add 00 07 08` installs several examples at once and `hmp example add --all`
installs every one. Each becomes a project of the workspace, and the regional DEM they share
is downloaded once.

## The model file

`hmp run` plays the file as one forward simulation, because it holds no `[calibration]` and no
`[overview]`. The file opens with the catchment. `[site]` names it and its gauge, `NANCON`.
Every series below reads that station: the discharge, and the SIM2 recharge and runoff averaged
over the catchment. `[metrics]` sets the window the discharge is scored on, 2001 and 2002, so
the year 2000 is spin-up.

```{hmp-toml}
:file: 04_streamflow_intermittence_in_transient/project.toml
:tables: site, metrics, simulation, simulation.time, simulation.process
```

The catchment is cut out of a regional DEM of 75 m, upstream of the outlet, after the
depressions of the DEM are breached. The domain is the box around the catchment, 172 by 157
cells, and the aquifer is one layer of 30 m under the ground.

```{hmp-toml}
:file: 04_streamflow_intermittence_in_transient/project.toml
:tables: geographic, geographic.catchment, domain.depth_model
```

`[data]` lists what the run reads, each from a file of the shared `data/` folder of the
workspace, named by `workspace:`. A folder source, `workspace:.`, reads the station that
{toml}`site.gauge` names.

```{hmp-toml}
:file: 04_streamflow_intermittence_in_transient/project.toml
:tables: data, data.dem.sources, data.hydrography.sources, data.hydrometry.sources, data.recharge.sources, data.runoff.sources
```

The flow is transient, so the heads move from one month to the next and the aquifer stores
water. The aquifer has one K, one Sy and one Ss. Every cell drains at the ground, with a
conductance that follows K. The first month is solved in steady state under the recharge of January 2000,
so the run starts from a wet winter water table.

```{hmp-toml}
:file: 04_streamflow_intermittence_in_transient/project.toml
:tables: flow, flow.param.K.field, flow.param.Sy.field, flow.param.Ss.field, flow.bc.drainage, flow.sinks_sources.recharge
```

The last part lists the figures and the files the run writes. A figure is a variable at a time,
with the layers drawn over it, or a preset. An export block says what to write and when, and
the format follows the data.

```{hmp-toml}
:file: 04_streamflow_intermittence_in_transient/project.toml
:tables: display, display.figure, export
```

## Run the file

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run project.toml
```
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("project.toml").open()
print(run.name)
```

A relative path is read from the folder you are in. `hmp.run` returns the
{doc}`Run <../reference/python/Run>`, whose reference page lists what it reads.
:::

::::

The run writes its figures to `runs/nancon_intermittence_mf6/figures/` and its exports to
`runs/nancon_intermittence_mf6/exports/`. The last line gives the name of the run and the NSE
of the discharge at the gauge, about 0.97.

Run an unchanged file a second time and nothing is computed. The command says which run is
already there, and `hmp run --force` computes it again. Edit the file, even one value, and the
second run is a new one, `runs/nancon_intermittence_mf6_v2/`, then `_v3`. A name is never
given out again: {doc}`hmp ls <../reference/cli/ls>` lists the versions,
{doc}`hmp diff <../reference/cli/diff>` compares them, and a deleted run goes to the project
trash.

## What can go wrong

| Message | Cause | What to do |
|---|---|---|
| `Outlet moved 130 m (limit 150 m) onto the flow network`, a `WARNING` line of every run | The coordinate of the file does not fall on a stream cell of the DEM, so the outlet moves to the cell with the largest flow accumulation in a window of {toml}`geographic.catchment.snap_dist`, here 150 m. | Nothing, here. A move close to the limit means the coordinate is far from the stream, so check it. |
| `Flow solver '<solver>' failed for run`, with a percent discrepancy and `did not converge` from the listing file | A very small Sy lets the water table move by metres in a month, and MODFLOW 6 does not converge in one time step. The script meets it with Sy = 0.001. | Cut each month in several time steps with {toml}`simulation.time.substeps_per_period`, as the script does with 4. |

## The script, step by step

`py1_run_and_plot.py` sits next to the file. It finds the project from its own location, so it
runs from any folder, and it can be stepped through cell by cell (`# %%`) in Spyder or VS Code.
It plays the model in a {doc}`lab <../how-to/work-in-the-lab>`, which builds the model in memory
one step at a time and writes no run until it is asked to.

After `load_data`, the forcing of the station is in memory, one value per month. The script
draws it.

```{literalinclude} /../../examples/projects/04_streamflow_intermittence_in_transient/py1_run_and_plot.py
:language: python
:start-after: "# %% The catchment and its forcing"
:end-before: "# %% The mesh on the relief, before the solve"
```

A run stopped at `prepare_solver` already stores the ground of every cell, so it draws the mesh
on the relief before anything is solved.

```{literalinclude} /../../examples/projects/04_streamflow_intermittence_in_transient/py1_run_and_plot.py
:language: python
:start-after: "# %% The mesh on the relief, before the solve"
:end-before: "# %% Three values of Sy, one run each"
```

Then Sy takes three values, and each one is kept as a run with the figures and the files of
`project.toml`. The value of the file gives the run of `project.toml`, so it is not solved
twice. With Sy = 0.001 the water table moves by metres in a month, and MODFLOW 6 needs four
time steps per month to converge.

```{literalinclude} /../../examples/projects/04_streamflow_intermittence_in_transient/py1_run_and_plot.py
:language: python
:start-after: "# %% Three values of Sy, one run each"
:end-before: "# %% The months of least and most seepage"
```

Each run gives the months when the catchment seeps the least and the most, and `run.figure`
draws the seepage cells and the water table of these two months from the sealed run, so
nothing is solved again. A small Sy lets the water table follow each month: the network swells
in winter and nearly dries in summer. A large Sy smooths the year.

```{literalinclude} /../../examples/projects/04_streamflow_intermittence_in_transient/py1_run_and_plot.py
:language: python
:start-after: "# %% The months of least and most seepage"
:end-before: "# %% How long each cell seeps, and the discharge"
```

The script takes about six minutes, most of it the run with the small Sy. Its figures land in
`summary/figures/`, beside the runs.

## Then

{doc}`calibrate-k` searches K on the mapped network of another catchment.
{doc}`../how-to/work-in-the-lab` lists every member of the lab, and
{doc}`../how-to/run-step-by-step` stops a run after a given step. The
{doc}`reference <../reference/parameters/index>` has one card per key of the file.
