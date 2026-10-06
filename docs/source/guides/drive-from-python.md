# Drive HydroModPy from Python

You run a project file from a script or a notebook, change a parameter and run again,
calibrate, and read the results back as pandas and xarray objects. Everything goes through
`import hydromodpy as hmp`. The functions run the same workflow steps as the `hmp`
command.

This page covers the five things a script does: run a file, edit a configuration in
memory, run one model many times, calibrate, and read results. It ends with the traps
that cost time.

## What you need first

- HydroModPy installed: {doc}`../get-started/install`.
- A project folder. It is the folder that holds `project.toml`, the file that marks the
  project root. Its catalog, `.hmp/index.duckdb`, sits inside it. Example 04,
  `examples/projects/04_streamflow_intermittence_in_transient`, is one.
- A configuration file that passes `hmp config check`. The blocks below start from
  `step4_transient.toml` of example 04. Run the Python from that folder.

```bash
hmp config check step4_transient.toml
```

A file that is valid prints `OK:` and its path.

## Pick the entry point

| You want to | Call | You get |
|---|---|---|
| Run one file, once | {doc}`hmp.run(path) <../reference/python/hmp-run>` | a `Run`, or `None` |
| Run a configuration you edited in memory | `hmp.run(cfg, name=...)` | a `Run`, or `None` |
| Run the same model many times, changing a parameter | {doc}`hmp.Project(cfg) <../reference/python/Project>` and `project.simulate(...)` | a `Run` per call |
| Calibrate | {doc}`hmp.calibrate(path) <../reference/python/hmp-calibrate>` or `project.calibrate(...)` | a report |
| Read finished runs | {doc}`hmp.open(folder) <../reference/python/hmp-open>` | a `Catalog` |
| Read one variable of a run | {doc}`hmp.read(run, name) <../reference/python/hmp-read>` | a DataArray, a Series or a GeoDataFrame |

A `Run` is one finished simulation, read from the catalog. The generated pages describe
every method: {doc}`Run <../reference/python/Run>`, {doc}`Catalog <../reference/python/Catalog>`,
{doc}`RunSet <../reference/python/RunSet>`. The whole list is in
{doc}`the Python reference <../reference/python/index>`.

## 1. Run a project file

```python
import hydromodpy as hmp

run = hmp.run("step4_transient.toml")
print(run.name, run.sim_id, run.status)
```

The path form takes the options of `hmp run`, written as Python names: `from_step`,
`until_step`, `dry_run`, `frozen`, `force`, `no_display`, `parallel` and `resume`. `headless`
and `no_lock` also work. A `dry_run` prints the plan, runs nothing and returns `None`.

The run is named by {toml}`simulation.name`. When the file leaves it empty, the name is
the file name without its extension, and without a leading `run_`. {toml}`simulation.if_exists`
says what happens when a run of that name already exists in the project.

```{hmp-resolved} simulation.name
:config: step4_transient.toml
```

```{hmp-resolved} simulation.if_exists
:config: project.toml
```

To name a run from a script, write the name in a file that inherits the first one:

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

`name=` is not an option of the path form: see the first row of
{ref}`what can go wrong <python-wrong>`. A file with another {toml}`workflow.mode` than
a simulation runs that workflow, and `hmp.run` returns its summary as a `dict`.

```{hmp-params}
workflow.mode
```

## 2. Change the configuration in memory

`HydroModPyConfig.from_toml` follows `base_config` and returns the object that
`hmp config check` validates. Each key of the file is an attribute.

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

The same change, written as a file:

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

```{hmp-params}
flow.param.K.field.value
display.figures
export
```

The project folder is the one {toml}`workspace.project_root` names. `from_toml` makes it
absolute, so the run lands in the same catalog whether you start it from the file or
from the object.

`cfg.to_toml(path)` writes the object back as a file. `HydroModPyConfig.from_dict` and
`from_json` build one from a complete payload.

## 3. Run the same model many times

`hmp.run` builds the catchment, the data and the mesh at every call. A `Project` builds
them once, at the first `simulate`, and every later call reuses them.

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

`hmp.Project` takes a path, a configuration object, a complete `dict` or a JSON string.
Building it is cheap: it validates the configuration and does no heavy work. Call
`project.prepare()` to build the model first.

What `project.simulate` takes:

- `name`, the run name. Without it the run is `run_0001`, then `run_0002` in the same
  `Project`.
- `K`, `Sy` and `Ss`, a new value for a parameter whose field is homogeneous. Another
  name stops with `Unknown parameter 'Foo'. Available: K, Ss, Sy`. The keywords `thickness`,
  `first_clim` and `properties` are also read.
- `until_step`, `from_step`, `resume`, `dry_run`, `frozen`, `no_display` and `parallel`,
  as in step 1. The steps are `validate`, `resolve`, `build_geographic`, `load_data`,
  `build_mesh`, `setup_process`, `prepare_solver`, `run_solver`, `extract`, `derive`,
  `display` and `export`.

A run with `K`, `Sy` or `Ss` runs the flow process alone. The other processes declared
in {toml}`simulation.process` do not run in it.

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

The same search can be written in Python. The dictionaries have the keys of the TOML
tables, so this call and the file below it describe one search:

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
{toml}`calibration.save_runs` keeps none.

## 5. Read the results

`hmp.open` takes the project folder and returns its catalog. It opens it read-only, so
reading never disturbs a run that is writing.

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
`cat[...]` reads, as does the command line (`hmp catalog point @last ...`). A name, a `sim_id` or a unique prefix of it
also resolve. `find` hides trashed runs and lists the newest first.

`hmp.read` picks the storage by itself:

| The variable is | You get |
|---|---|
| a field in Zarr, such as `head` | a lazy `xarray.DataArray`; a `numpy` array when `time` is an integer |
| a series, such as `discharge` | a `pandas.Series` |
| a geographic feature, such as `watershed` | a `geopandas.GeoDataFrame` |

```python
head = hmp.read(run, "head")                       # every period, lazy
last = hmp.read(run, "head", time=-1, layer=0)     # the last period, top layer
q_sim = hmp.read(run, "discharge")
```

A run stores its fields by stress period, not by date. Period `i` runs from
`run.periods.edges[i]` to `run.periods.edges[i + 1]`. To read a date, turn it into a
period index first, and use the same index for every field:

```python
step = run.periods.step_at("2002-10-15")
seepage = hmp.read(run, "seepage_mask", time=step)
months = run.periods.edges[:-1]                    # the start of each period
```

The simulated `discharge` Series is indexed on the end stamp of each period. Put it on
`edges[:-1]` before you compare it with a gauge averaged by month.

`hmp.figure` and `hmp.export` take dates directly:

```python
from hydromodpy.display import names

fig = hmp.figure(run, "seepage_map", time="2002-10-15")   # a matplotlib Figure
files = hmp.export(run, ["watertable_depth"], time="2001-01-15")
print(len(names()), "figures")
```

These calls follow the {toml}`display.figures` and {toml}`export` tables of the file.
{doc}`hmp.figure <../reference/python/hmp-figure>` and
{doc}`hmp.export <../reference/python/hmp-export>` give every argument. A value at one place
is in {doc}`read-a-value-at-a-point`. What a run writes is in {doc}`results-and-exports`.

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
`ConfigMissingError`.

## Check that it worked

- `hmp config check file.toml` before any Python, as above.
- `run.status` is `completed` for a finished run. `hmp catalog ls` lists the runs of the
  project, with the same names.
- `run.params` holds the parameter values the run used, and `run.metrics` its scores.
  After a loop, read both on each run and check that the values differ the way you set them.
- `cat.frame` shows one row per run. A run you replaced has the status `trashed`.
- The run folder is `runs/<run.name>/` in the project folder.

(python-wrong)=
## What can go wrong

**`hmp.run(path, name="x")` stops with a `TypeError`.**

```text
TypeError: run_simulation() got an unexpected keyword argument 'name'
```

The path form has no `name`. Write the name in {toml}`simulation.name`, or pass a
configuration object: `hmp.run(cfg, name="x")`.

**`hmp.run` never skips a run.** Every call computes and registers a new run, even when
nothing changed. The `hmp run` command has a message for an identical completed run, but
the check compares a hash that includes the scratch folder of the process, so two runs
never match and the message does not appear. Name the run, and let {toml}`simulation.if_exists` decide what
becomes of the old one. With the default, the names go `x`, `x.v2`, `x.v3`. With
`replace`, the old run goes to the trash and keeps its name, and the new run takes the
next version, `x.v2`. With `fail`, the second run
stops with:

```text
Simulation 'x' already exists in project 'p' (existing sim_id ...). Use if_exists='replace' or 'version' to proceed.
```

**A configuration without a name makes `run_0001`.** `hmp.run(cfg)` and
`project.simulate()` do not read {toml}`simulation.name`. The name comes from a counter
that starts at 1 in each `Project`. A second script gets `run_0001.v2`. Always pass
`name=`.

**`cat["x"]` returns the wrong run.** The exact name wins, and a trashed run keeps its
name. After a `replace`, `cat["x"]` is the old trashed run, with status `trashed`. Use
`cat.find(name_stem="x")[0]` for the newest live run, `cat["x.v2"]` for a version, or
`cat.latest()`.

**A `Run` fails with `Connection already closed`.** A `Run` reads through the catalog of
the object that gave it to you. When a `Project` leaves its `with` block, it closes that
catalog, and every `Run` taken from it is dead:

```text
duckdb.ConnectionException: Connection already closed
```

Keep the `sim_id`, then open the catalog again, as in step 3. `hmp.run` is safe: it
hands you a `Run` bound to a fresh catalog. Between two `simulate` calls in one `with`
block, the `Run` objects you already hold stay valid.

**`hmp.run` returns `None` although the run finished.** `None` is the answer of a
`dry_run`. It is also what you get when the catalog of the project cannot be opened at
the folder of the file. Open it yourself with `hmp.open(folder)`.

**`hmp.open` finds no catalog.**

```text
FileNotFoundError: No catalog at <folder>/.hmp. Run a workflow there first, or pass create=True to initialise an empty catalog.
```

Give a project folder, not a workspace root. A workspace root holds no index. If the
index is locked or corrupt, `hmp catalog reindex` rebuilds it from the run folders.

**A write on a run is refused.** `hmp.open` is read-only by default. `run.tag(...)`,
`run.note(...)` and `run.delete()` stop with `Catalog at <path> is open read-only; writes
are refused.` Open with `hmp.open(folder, read_only=False)`.

**`cat["nope"]` and `cat.latest()` raise.** `SimulationNotFoundError`: ``Reference 'nope'
not found. Run `hmp catalog ls` to list known runs.`` and, on an empty catalog,
`KeyError: 'No completed simulation in the catalog'`.

**`hmp.read(run, "head", time="2002-10-15")` returns every period.** The `time` of
`hmp.read` is an integer or a slice. A date is ignored without an error. Use
`run.periods.step_at(date)`. An unknown variable raises `FieldNotFoundError`, with a
message that starts `Variable 'x' not found in any backend`.

**A project in a `dict` is refused.** `hmp.Project(dict)` validates the whole
configuration. A payload with only a few sections fails with `Field required` for each
section it leaves out. Start from `cfg.model_dump(mode="json")` of a loaded file.

## Next

- Pick the stages and the criteria of a calibration: {doc}`calibrate`.
- Find, compare and clean runs from the command line: {doc}`find-compare-and-clean-runs`.
- Write a variant of a file instead of editing it in Python: {doc}`inheritance`.
- Every function and class: {doc}`the Python reference <../reference/python/index>`.
- A model that runs, step by step: {doc}`../get-started/staircase/index`.
