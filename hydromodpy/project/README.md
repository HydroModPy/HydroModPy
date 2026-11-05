# `hydromodpy/project`

A project driven from Python: one object, `Project`, that holds a validated
configuration, builds the model once, and runs it as often as asked. The same
package carries the adapters that bind a workflow name (`simulation`,
`calibration`, ...) to a `Project`, which `hmp run` and `hmp.run` use.
`Project` is not an execution engine. It calls the workflow layer, so the
interactive route and the TOML route share the same steps.
This file is the map of the package: what each module answers, the import
rules, how a run goes through it, and where to add what.

## Parts

| part | answers |
|---|---|
| `facade.py` | the public verbs of `Project`: `prepare`, `simulate`, `calibrate`, `spinup`, `rerun`, the model-phase verbs, the launch verbs of a `[sites]` project (`plan`, `launch`, `status`, `collect`, `publish`), the read-only views, `close`; `_execute`, the worker verb of `hmp run` |
| `opening.py` | what opens and shows a `Project` without being one of its verbs: `open_project` (what `hmp.open` calls on a project folder), `configure_opened` (its `project.toml`, read on the first model verb), `resolve_config` (the polymorphic config input), `refreshed_index` (the index brought up to date), `project_repr` and `project_html` |
| `calibrate.py` | the routing behind `Project.calibrate` and `hmp.calibrate` on a path: a TOML file to the staged or the CLI runner (`calibrate_a_file`), a declaration held in memory (`parameters=`, `protocol=`, the `[calibration]` of the project) to the programmatic runner (`calibrate_project`) |
| `state.py` | where the runtime state of a `Project` lives (`ProjectState`), and which attribute names `Project` forwards to it (`PROJECT_ATTR_TO_STATE_FIELD`) |
| `phases.py` | the model-phase verbs as free functions: `configure`, `setup_workspace`, `build_geographic`, `load_data`, `reload_data`, `rebuild_geographic`, `build_mesh`, `open_catalog` (the index, read only, and only when it exists) |
| `runner.py` | `ProjectRunner`: one run through the workflow `Pipeline` (step window, resume, overrides, run naming; the attempt protocol `run_attempt` and `SealedRun` live in `workflow/record/attempt.py`, the replay checks in `workflow/replay_checks.py`); `execute` is the worker verb, `run` adds the index and the `Run` view, `draft` says what a run would do |
| `run_overrides.py` | the `set=` of `simulate` as dotted changes of the configuration of the run, the names of `hmp config targets` |
| `catalog.py` | `ProjectCatalog`: the index binding of a project (`store`, `data`, `runs`) and its `close` |
| `accessors.py` | the read-only views `project.data` (`ProjectDataAccessor`) and `project.runs` (`ProjectRunsAccessor`), the campaign reads behind `project.cases`, `.sites`, `.best_runs` and `.sessions` (`ProjectSessions`), and `Workspace`, what `hmp.open` returns on a workspace root; the index itself is `project.store`, a `Catalog`, and `project[ref]` is one `Run` |
| `launch/` | the launcher of a `[sites]` project: lease, case selection, prepare, local launch, SLURM array, status, collect into `summary/`. See [launch/README.md](launch/README.md) |
| `exchange/` | publish a run with its inputs, install a published copy, replay it from its own bytes. See [exchange/README.md](exchange/README.md) |
| `dispatch/` | the adapters that need `Project` and that lower layers must not import: workflow name to run function, rerun provider. See [dispatch/README.md](dispatch/README.md) |
| `spinup.py` | `run_spinup`: repeat a forcing window, each cycle restarting from the last, until heads and lake stages stop moving |

## Import rules

`project` sits above the layer matrix, like `cli`. `layer_matrix.yaml` lets it
import every layer, itself included. Today it imports `analysis`,
`calibration`, `config`, `core`, `data`, `physics`, `results`, `simulation`,
`solver`, `spatial` and `workflow`. Two rules matter more than the table:

1. No lower layer imports `project`. Only the package root (lazy, a tolerated
   edge in `layer_matrix.yaml`) and `cli` do. A lower layer that needs a
   `Project` declares a Protocol and receives the adapter at start-up.
2. The adapters are wired in `hydromodpy/_bootstrap.py`:
   `ProjectRerunProvider` into `results.run.rerun_contract`. A new adapter
   gets a hook there.

No `project_layout.yaml` orders the modules inside the package. The shape is
the one `__init__.py` documents: `facade.py` composes `ProjectRunner`,
`ProjectCatalog` and the functions of `phases.py`. The other modules import
`Project` under `TYPE_CHECKING` only, except the adapters of `dispatch/`,
which import it inside a function. `launch/` and `exchange/` never import
`Project`. `attempt` and `replay_checks` left this package for `workflow`
(`workflow/record/attempt.py`, `workflow/replay_checks.py`) because they never
needed `Project`. The module `hydromodpy.project.launch.slurm` keeps its name
because the frozen `launch/templates/*.sh` call it.

## Tree

```
hydromodpy/project/
  __init__.py       Project, ProjectRunner, ProjectCatalog, the two accessors
  facade.py         Project and its verbs
  opening.py        open_project, resolve_config, repr and html of a Project
  calibrate.py      routing of Project.calibrate
  state.py  phases.py  runner.py  run_overrides.py  spinup.py
  catalog.py  accessors.py
  dispatch/         workflow.py  rerun.py                      (README.md)
  launch/           the [sites] launcher, SLURM and summary/   (README.md)
  exchange/         share.py  install.py  replay.py            (README.md)
```

## How a run goes through it

1. **Construct.** `Project(config)` validates the configuration (a TOML path,
   a `HydroModPyConfig`, a dict or a JSON string) through `phases.configure`.
   Nothing heavy runs.
2. **Build the model once.** The first `simulate`, `prepare` or runtime
   accessor calls `_ensure_model_built`: `build_geographic`, `load_data`,
   `build_mesh`. The per-phase verbs do the same one phase at a time.
3. **Execute.** `_execute(name=..., set=...)` is the worker verb. It claims
   `runs/<name>/` through `run_attempt` (a completed name gets `.vN`, a failed
   or aborted one continues as the next attempt, a running one with a fresh
   pulse is refused, `fresh` moves everything aside, `force` takes a stale
   claim), builds the workflow `Pipeline` over `standard_steps()` and returns
   a `SealedRun`. It never opens the index. `from_step`, `until_step`,
   `resume` and `frozen` act on the step window of that pipeline.
   A run stopped before `setup_process` builds no model; a window ended by
   `until_step` leaves the outcome `partial`.
4. **Simulate.** `simulate(...)` is `_execute` followed by `index_new_runs`
   and the `Run` view of the new directory through `Catalog(project_root)`,
   opened read only.
5. **Calibrate.** `calibrate` routes to the calibration runners: the phased
   runner for phases, the programmatic runner for keyword arguments, the CLI
   runner for one search from a file.
6. **Read back.** `project.runs` and `project.data` list what the index
   holds; `Run` objects come from `results`. The index is derived from
   `runs/` and `sessions/` and is never written by a run.
7. **Close.** `close()` closes the index. `with Project(...) as project`
   does it.

From a terminal, `hmp run` and `hmp.run` call `dispatch.workflow.dispatch_workflow`
with the workflow the file declares. `run_simulation` opens a `Project`,
skips a plain run whose resolved config already sealed under the same name
(read from the manifests, unless `force`), and calls `Project.execute`; the
CLI indexes the new directory once the worker has returned.

A file that declares `[sites]` goes through `launch/` instead (details in [launch/README.md](launch/README.md)): `run_plan`
takes the lease, writes the plan when the current one is out of date, runs
the prepare phase, then starts one `hmp run plan/<hash>/<case>.toml --frozen`
process per case within the budget of `[sites.run] parallel`, writes the
journal of the launch and indexes each case when it ends.

## Where to add what

| to add | where |
|---|---|
| a public verb on `Project` | a method in `facade.py` that delegates to `runner.py`, `phases.py` or a new module; no business logic in the facade |
| a model-phase verb | a function in `phases.py` and a thin method on `Project` |
| a run option | a keyword of `ProjectRunner.execute`, and the same keyword on `execute`, `simulate` and on `dispatch/workflow.run_simulation` |
| a way an attempt ends | a status of `Outcome` (`results/outcome.py`) and its branch in `workflow/record/attempt.py` (`run_attempt`) |
| a workflow name | a `run_*` function and an entry in `DISPATCH` in `dispatch/workflow.py`; the name list itself lives in `hydromodpy/workflow/dispatch.py` |
| a launcher step, a scheduler or a `summary/` table | `launch/`, see its README |
| a publish, install or replay step | `exchange/`, see its README |
| a provider for a lower layer | a class in `dispatch/`, a Protocol and a `register_*` function in the lower layer, a hook in `hydromodpy/_bootstrap.py` |
| runtime state on `Project` | a field of `ProjectState` and its name in `PROJECT_ATTR_TO_STATE_FIELD` |
