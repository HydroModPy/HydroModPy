# Drive HydroModPy from Python

```{hmp-task}
Task
: Run a project file from a script or a notebook, change a parameter and run again, calibrate, and read the results back as pandas and xarray objects.

Time
: Minutes to write. Each run costs what it costs from the command line.

Needs
: HydroModPy installed ({doc}`../get-started/install`), and a project folder: the folder that holds `project.toml`. Example 04, `examples/projects/04_streamflow_intermittence_in_transient`, is one. A file that passes `hmp config check`. The blocks below start from `step4_transient.toml`. Run the Python from that folder.

Gives
: A `Run` for each simulation, a catalog you can query, and a loop that sweeps a parameter on one model that is built once.
```

Everything goes through `import hydromodpy as hmp`. The functions run the same workflow
steps as the `hmp` command. This page covers the five things a script does: run a file, edit
a configuration in memory, run one model many times, calibrate, and read results.

```bash
hmp config check step4_transient.toml
```

A file that is valid prints `OK:` and its path.

## Pick the entry point

| You want to | Call | You get |
|---|---|---|
| Run one file, once | {doc}`hmp.run(path) <../reference/python/hmp-run>` | a `Run`, or `None` for a dry run |
| Run a configuration you edited in memory | `hmp.run(cfg, name=...)` | a `Run`, or `None` for a dry run |
| Run the same model many times, changing a parameter | {doc}`hmp.Project(cfg) <../reference/python/Project>` and `project.simulate(...)` | a `Run` per call |
| Calibrate | {doc}`hmp.calibrate(path) <../reference/python/hmp-calibrate>` or `project.calibrate(...)` | a report |
| Read finished runs | {doc}`hmp.open(folder) <../reference/python/hmp-open>` | a `Catalog` |
| Read one variable of a run | {doc}`hmp.read(run, name) <../reference/python/hmp-read>` | a DataArray, a Series or a GeoDataFrame |

A `Run` is one finished simulation, read from the catalog. The generated pages describe
every method: {doc}`Run <../reference/python/Run>`, {doc}`Catalog <../reference/python/Catalog>`,
{doc}`RunSet <../reference/python/RunSet>`. The whole list is in
{doc}`the Python reference <../reference/python/index>`. The relations between these objects
are on {doc}`../reference/python/objects`.

## 1. Run a project file

::::{tab-set}
:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.run("step4_transient.toml")
print(run.name, run.sim_id, run.status)
```

The path form takes the options of `hmp run`, written as Python names: `name`, `from_step`,
`until_step`, `dry_run`, `frozen`, `force`, `no_display`, `parallel` and `resume`. `headless`
and `no_lock` also work. A `dry_run` prints the plan, runs nothing and returns `None`. A
parameter such as `K=1e-5` is not an option of the path form: see step 3.
:::
:::{tab-item} Command line
```bash
hmp run step4_transient.toml
```

The command takes the same options as flags: `--from`, `--until`, `--dry-run`, `--frozen`,
`--force`, `--resume`. The flags are listed in the {doc}`CLI reference <../reference/cli/run>`.
:::
::::

The run is named by `name=` when you give it, else by {toml}`simulation.name`. When the file
leaves the key empty, the name is the file name without its extension, and without a leading
`run_`. {toml}`simulation.if_exists` says what happens when a run of that name already exists
in the project.

```{hmp-resolved} simulation.name
:config: step4_transient.toml
```

```{hmp-resolved} simulation.if_exists
:config: project.toml
```

A run identical to a completed one is not computed again. `hmp.run` returns the existing
`Run` and logs a warning that names it: `Config identical to completed run '<name>' [<id8>];
nothing to do. Pass force=True to run it again.` Identical means the same resolved
configuration, the same name and no parameter override. `force=True` computes anyway.
{doc}`find-and-compare-runs` gives the rule and its limits.

To name a run from a script without `name=`, write the name in a file that inherits the first
one:

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_python_try"
if_exists = "replace"
```

```{hmp-params}
simulation.name
simulation.if_exists
```

A file with another {toml}`workflow.mode` than a simulation runs that workflow, and
`hmp.run` returns its summary as a `dict`.

```{hmp-params}
workflow.mode
```

## 2. Change the configuration in memory

`HydroModPyConfig.from_toml` follows `base_config` and returns the object that
`hmp config check` validates. Each key of the file is an attribute.

::::{tab-set}
:::{tab-item} Python
```python
import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

cfg = HydroModPyConfig.from_toml("step4_transient.toml")

cfg.flow.param["K"].field.value = 2e-5
cfg.display.figures = ["hydrograph_log_nse", "seepage_map"]
cfg.export = []

run = hmp.run(cfg, name="nancon_variant")
```

Each assignment is validated at once. A bad value stops on the line that wrote it, not at
the run. A value that is not a number gives:

```text
K.value must be numeric or '<number> <unit>' (for example '1.0 m').
```

A figure name that does not exist gives `display.figures references unknown figure(s): ...`
and lists the registered names. Assign a whole new list to {toml}`display.figures`
or {toml}`export`. An `append` on the list is not validated.
:::
:::{tab-item} TOML file
```toml
base_config = "step4_transient.toml"

[flow.param.K.field]
value = 2e-5

[display]
figures = ["hydrograph_log_nse", "seepage_map"]
```

K is a number in the unit the field declares. The inherited unit stays:

```{hmp-resolved} flow.param.K.field.value
:config: step4_transient.toml
```
:::
::::

```{hmp-params}
flow.param.K.field.value
display.figures
export
```

The project folder is the one {toml}`workspace.project_root` names. `from_toml` makes it
absolute, so the run lands in the same catalog whether you start it from the file or
from the object.

`cfg.to_toml(path)` writes the object back as a file. `HydroModPyConfig.from_dict` and
`from_json` build one from a payload that validates as a whole file. A configuration object
carries its own `[simulation] name`, so `hmp.run(cfg)` names the run like the file does.

## 3. Run the same model many times

`hmp.run` builds the catchment, the data and the mesh at every call. A `Project` builds
them once, at the first `simulate`, and every later call reuses them. A parameter override
such as `K=k` belongs here, or in the object form of `hmp.run(cfg, K=...)`. On a path, it is
refused:

```text
TypeError: hmp.run('step4_transient.toml') takes no parameter override (K). Write the value in the TOML file, or load it with hydromodpy.config.HydroModPyConfig.from_toml and pass the configuration object: hmp.run(cfg, K=...). Accepted options: dry_run, force, from_step, frozen, name, no_display, parallel, resume, until_step.
```

```python
import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

cfg = HydroModPyConfig.from_toml("step4_transient.toml")
cfg.export = []

sim_ids = []
with hmp.Project(cfg, no_display=True) as project:
    for k in [1e-5, 5e-5, 2e-4]:
        run = project.simulate(name=f"nancon_k_{k:.0e}", K=k)
        sim_ids.append(run.sim_id)

cat = hmp.open(".")
runs = [cat[sim_id] for sim_id in sim_ids]
```

`hmp.Project` takes a path, a configuration object, a `dict` or a JSON string, validated
like a file. Building it is cheap: it validates the configuration and does no heavy work.
Call `project.prepare()` to build the model first.

What `project.simulate` takes:

- `name`, the run name. Without it the run takes {toml}`simulation.name`. A name that
  repeats takes the next version, `x.v2`. A configuration that names no run gets
  `run_0001`, then `run_0002` in the same `Project`.
- `K`, `Sy` and `Ss`, a new value for a parameter whose field is homogeneous. Another
  name stops with `Unknown parameter 'Foo'. Available: K, Ss, Sy`. The keywords `thickness`,
  `first_clim` and `properties` are also read.
- `until_step`, `from_step`, `resume`, `dry_run`, `frozen`, `no_display` and `parallel`,
  as in step 1. The steps are `validate`, `resolve`, `build_geographic`, `load_data`,
  `build_mesh`, `setup_process`, `prepare_solver`, `run_solver`, `extract`, `derive`,
  `display` and `export`.

`project.simulate` always computes: a sweep or a loop is never skipped. A run with `K`, `Sy`
or `Ss` runs the flow process alone. The other processes declared in
{toml}`simulation.process` do not run in it.

`no_display=True` on the `Project` skips the figures of every run. `headless=True` also
drops the postprocess steps.

Inside the `with` block, `project.runs` lists the runs of this project and
`project.data` the loaded input data:

```python
with hmp.Project(cfg) as project:
    project.simulate(name="probe_1", K=1e-5)
    project.runs.list()        # DataFrame, one row per run of the project
    project.runs.latest()      # a Run, or None
    project.runs.best("nse")   # the best Run on a metric
    project.data.list()        # input variables already loaded
    project.data.missing()     # declared in [data] and not loaded
```

A `Run` taken from a `Project` stays readable after the `with` block: it reopens the catalog
read-only on its next read. Example 04 ships `py4_sweep_k.py`, a sweep of this shape.

```{hmp-params}
simulation.process
```

## 4. Calibrate

A calibration file has its own guide: {doc}`calibrate`. From Python it is one call.

```python
import hydromodpy as hmp

hmp.calibrate("run_calibration.toml", list_phases=True)   # the stages, nothing solved
hmp.calibrate("run_calibration.toml", expand=True)        # the section a protocol writes
report = hmp.calibrate("run_calibration.toml")            # the search
```

`list_phases` and `expand` answer without solving. `phase="name"` runs one stage of a
staged calibration. `expand` needs a path, not a configuration object. What comes back
depends on the file: a `dict` for a single stage, a report object for a file with phases.

The same search can be written in Python or as a file. The dictionaries have the keys of the
TOML tables, so the call and the file describe one search:

::::{tab-set}
:::{tab-item} Python
```python
with hmp.Project(cfg) as project:
    report = project.calibrate(
        method="optuna",
        max_iter=30,
        seed=42,
        parameters={"K": {"bounds": [1e-7, 1e-3]}},
        outputs={"hydrograph": {"support": "point", "variable": "discharge", "observes": "NANCON"}},
        objective_blocks=[{"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["hydrograph"]}],
    )
print(report.best_parameters, report.best_objective, report.best_sim_id)
```
:::
:::{tab-item} TOML file
```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration]
method = "optuna"
max_iter = 30
seed = 42

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["hydrograph"]
```
:::
::::

```{hmp-params}
calibration.method
calibration.max_iter
calibration.seed
calibration.parameters
calibration.outputs
calibration.objective_blocks
```

`project.calibrate(config_path="file.toml")` runs a file on a project you already hold.
With neither `config_path` nor `parameters`, it uses the `[calibration]` section of the
project configuration. `best_sim_id` is the promoted best run, and `None` when
{toml}`calibration.save_runs` keeps none. The control figure of a calibration is the
hydrograph of the best run on a log axis, with the scoring window shaded:

```{figure} /_static/figures/guides/hydrograph_log_nse.webp
:alt: Simulated and observed monthly discharge on a log axis, with the scoring window 2001 to 2002 shaded.
:width: 100%

`hydrograph_log_nse` of the calibrated run of example 04. The score counts the 24 samples of
the shaded window.
```

## 5. Read the results

`hmp.open` takes the project folder and returns its catalog. It opens it read-only, so
reading never disturbs a run that is writing. Given a workspace root instead of a project
folder, it names the projects under it that have a catalog.

```python
import hydromodpy as hmp

cat = hmp.open(".")                       # the folder of project.toml, or a folder below it
cat.frame                                 # one row per run, as a DataFrame
run = cat.latest()                        # newest completed run
run = cat["@best:nse"]                    # best on a metric, outlet station first
run = cat.find(name_stem="nancon_python_try")[0]   # newest live run of a name
sims = cat.find(solver="modflow6", status="completed")   # a RunSet
```

`@last`, `@last~N`, `@best:METRIC`, `@worst:METRIC` and `@running` are selectors that
`cat[...]` reads, as does the command line (`hmp catalog point @last ...`). A name, a
`sim_id` or a unique prefix of it also resolve. `@best` follows the direction of the metric:
the lowest `rmse`, the highest `nse`. `find` hides trashed runs and lists the newest first.
A bare name finds the exact name first, then the newest live version of it, and a trashed
run only when nothing live holds the name.

`hmp.read` picks the storage by itself:

| The variable is | You get |
|---|---|
| a field in Zarr, such as `head` | a lazy `xarray.DataArray`; a `numpy` array when `time` names one period |
| a series, such as `discharge` | a `pandas.Series` |
| a geographic feature, such as `watershed` | a `geopandas.GeoDataFrame` |

```python
head = hmp.read(run, "head")                       # every period, lazy
last = hmp.read(run, "head", time=-1, layer=0)     # the last period, top layer
oct_2002 = hmp.read(run, "head", time="2002-10-15", layer=0)   # the period that holds the date
q_sim = hmp.read(run, "discharge")
```

`time` takes an index, a date (a string, a `date`, a `datetime`, a `Timestamp` or a
`numpy.datetime64`), `"first"` or `"last"`. A date reads the stress period that holds it.
A run stores its fields by stress period, not by date: period `i` runs from
`run.periods.edges[i]` to `run.periods.edges[i + 1]`, and
`run.periods.step_at("2002-10-15")` turns a date into its index. A series refuses `time`: window
it with `sel={"period": ("2002-01-01", "2002-12-31")}`. The simulated `discharge` Series is
indexed on the end stamp of each period. Put it on `run.periods.edges[:-1]` before you compare
it with a gauge averaged by month ({doc}`/theory/time-alignment`).

`hmp.figure` and `hmp.export` take dates directly:

```python
from hydromodpy.display import names

fig = hmp.figure(run, "seepage_map", time="2002-10-15")   # a matplotlib Figure
files = hmp.export(run, ["watertable_depth"], time="2001-01-15")
print(len(names()), "figures")
```

The call draws the seepage cells of October 2002. The control figure is this map:

```{figure} /_static/figures/guides/seepage_map.webp
:alt: Seepage cells of the Nançon catchment in October 2002, with the outlet marked.
:width: 60%

`seepage_map` of the calibrated run of example 04 at 2002-10-15.
```

These calls follow the {toml}`display.figures` and {toml}`export` tables of the file.
{doc}`hmp.figure <../reference/python/hmp-figure>` and
{doc}`hmp.export <../reference/python/hmp-export>` give every argument. A value at one place
is in {doc}`read-a-value-at-a-point`. What a run holds is in {doc}`read-the-results`, and how
to write it out in {doc}`export-results`.

## 6. Run a past run again

`Project.rerun` rebuilds the configuration from the snapshot a run stored, applies a patch
and runs it. The new run records the old one as its parent.

```python
run2 = hmp.Project.rerun(
    run,
    name="nancon_k_high",
    config_overrides={"flow": {"param": {"K": {"field": {"value": 1e-4}}}}},
)
print(run2.parent.name)
```

`config_overrides` is a nested patch on the stored configuration. A key that is not a
field of the configuration stops the call. A run without a stored snapshot raises
`ConfigMissingError`. `run.hydromodpy_config` on a snapshot that this version no longer
validates raises a `ValueError` that points to `run.config_snapshot`.

## How to check it worked

- `hmp config check file.toml` before any Python, as above.
- `run.status` is `completed` for a finished run. `hmp catalog ls` lists the runs of the
  project, with the same names.
- `run.params` holds the parameter values the run used, and `run.metrics` its scores.
  After a loop, read both on each run and check that the values differ the way you set them.
- `cat.frame` shows one row per run. A run you replaced has the status `trashed`.
- The run folder is `runs/<run.name>/` in the project folder.
- Run the same call twice. The second logs `Config identical to completed run` and returns
  the first run.

## What can go wrong

| What you see | Cause | Fix |
|---|---|---|
| `TypeError: hmp.run('<file>.toml') takes no parameter override (K). Write the value in the TOML file, or load it with ...` | A parameter keyword on a path. | Write the value in the file, or pass a configuration object: `hmp.run(cfg, K=...)`. |
| The run is not computed and the log says `Config identical to completed run '<name>' [<id8>]; nothing to do. Pass force=True to run it again.` | The run is identical to a completed one. | Change the file, or the name, or pass `force=True`. A `Project.simulate` call is never skipped. |
| `CatalogError`: `The run [<id8>] finished, but the catalog at <root> cannot be opened to hand it back: <cause>. Open it with hmp.open('<root>') and read the run by its id.` | The simulation finished and its catalog cannot be opened. `None` now means a dry run only. | Open the catalog yourself, as the message says. `hmp catalog reindex` rebuilds a corrupt index. |
| `FileNotFoundError: No catalog at <folder>/.hmp. Run a workflow there first, or pass create=True to initialise an empty catalog.` | `hmp.open` found no index. | Give a project folder. A workspace root names its projects in the message. If the index is locked or corrupt, `hmp catalog reindex`. |
| `ReadOnlyError: Catalog at <path> is open read-only; writes are refused.` from `run.tag(...)`, `run.note(...)`, `run.delete()` | `hmp.open` is read-only by default. | `hmp.open(folder, read_only=False)`. |
| The log says `audit emission failed for export` after `hmp.export(...)` | The export ran on a catalog opened read-only, so the audit log could not record it. | `hmp.open(folder, read_only=False)` before you export, when the export must appear in `hmp audit`. |
| `WriteConflictError: The index '<path>' is already open in this process in another mode.` | One process opened the same project read-only and then writable (or the reverse). | Close the first handle, or open both the same way. |
| ``SimulationNotFoundError: Reference 'nope' not found. Run `hmp catalog ls` to list known runs.`` | The name is not in the catalog, or the run is in the trash. | `hmp catalog ls`, or `cat.find(name_stem="nope")`. |
| `KeyError: 'No completed simulation in the catalog'` from `cat.latest()` | The catalog holds no completed run. | Run something, or check `cat.frame["status"]`. |
| `SimulationNotFoundError: '@best:<m>': Metric '<m>' has no declared direction ...` | The metric is not ranked. | Name a metric that has a direction ({doc}`find-and-compare-runs`). |
| `TimeSelectionError: 1999-01-01 is outside the record: ...` from `hmp.read(time=...)` | The date is outside the run. | Use a date inside the record. |
| `ValueError: 'discharge' is a series, and time= selects a period of a field. Use sel={"period": (start, end)}.` | `time=` on a series or a feature. | Window the series with `sel`. |
| `TypeError: time must be a period index, a slice of indexes, a date, 'first' or 'last'; got <type>.` | A `time` of another kind. | Pass an integer, a date, `"first"` or `"last"`. |
| `FieldNotFoundError: Variable 'x' not found in any backend ...` | An unknown variable. | `hmp export <run> --list` prints the names a run holds. |
| `Unknown parameter 'Foo'. Available: K, Ss, Sy` | A keyword that `simulate` does not know. | Use `K`, `Sy`, `Ss`, `thickness`, `first_clim` or `properties`. |
| `display.figures references unknown figure(s): ...` | A figure name that does not exist. | The message lists the registered names. |

## Next

- Pick the stages and the criteria of a calibration: {doc}`calibrate`.
- Find, compare and clean runs from the command line: {doc}`find-and-compare-runs`.
- Run a long file and come back to it: {doc}`run-in-the-background`.
- Sweep a parameter without writing a loop: {doc}`sweep-a-parameter`.
- Write a variant of a file instead of editing it in Python: {doc}`inheritance`.
- Every function and class: {doc}`the Python reference <../reference/python/index>`.
- A model that runs, step by step: {doc}`../get-started/staircase/index`.
