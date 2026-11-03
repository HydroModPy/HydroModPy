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
| `facade.py` | the public verbs of `Project`: `prepare`, `execute`, `simulate`, `calibrate`, `spinup`, `rerun`, the model-phase verbs, the launch verbs of a `[sites]` project (`plan`, `run`, `status`, `collect`, `publish`), the read-only views, `close`; `open_project`, what `hmp.open` calls on a project folder |
| `state.py` | where the runtime state of a `Project` lives (`ProjectState`), and which attribute names `Project` forwards to it (`PROJECT_ATTR_TO_STATE_FIELD`) |
| `phases.py` | the model-phase verbs as free functions: `configure`, `setup_workspace`, `build_geographic`, `load_data`, `reload_data`, `rebuild_geographic`, `build_mesh`, `open_catalog` (the index, read only, and only when it exists) |
| `attempt.py` | `run_attempt`: the attempt protocol around one run (claim of the directory under `runs/`, heartbeat, outcome closed as `completed`, `partial`, `failed` or `aborted` on exit); `SealedRun`, what a worker returns |
| `runner.py` | `ProjectRunner`: one run through the workflow `Pipeline` (step window, resume, dry run, overrides, run naming); `execute` is the worker verb, `run` adds the index and the `Run` view |
| `run_overrides.py` | the keywords of `simulate` as dotted changes of the configuration of the run, the names of `hmp config targets` |
| `replay_checks.py` | what a replay checks against the run it repeats: the digests of its record, `config.resolved.toml`, the solver binary |
| `catalog.py` | `ProjectCatalog`: the index binding of a project (`store`, `data`, `runs`) and its `close` |
| `accessors.py` | the read-only views `project.data` (`ProjectDataAccessor`) and `project.runs` (`ProjectRunsAccessor`), the campaign reads behind `project.cases`, `.sites`, `.best` and `.sessions` (`ProjectSessions`), and `Workspace`, what `hmp.open` returns on a workspace root; the index itself is `project.store`, a `Catalog`, and `project[ref]` is one `Run` |
| `spinup.py` | `run_spinup`: repeat a forcing window, each cycle restarting from the last, until heads and lake stages stop moving |
| `lockfile.py` | `write_project_lockfile`: the `hydromodpy.lock` of the project |
| `launch/` | the launcher of a `[sites]` project: `local.py` (`plan_project`, `run_plan`: plan, prepare, one process per case, count, index), `prepare.py` (the data of every case before any solve, the private caches merged, `hydromodpy.lock` written once), `lease.py` (`.hmp/launcher.lease`, one launcher per project), `journal.py` (`jobs/<stamp>-<scheduler>/` and its `journal.jsonl`), `children.py` (the worker processes and their outcome when they die silent), `env.py` (the environment and the thread budget of a case), `status.py` (`project_status`, read from the plan and the outcomes, never the index), `slurm.py` and `templates/` (the frozen scripts of `hmp project array`) |
| `summary.py` | `collect_project`: `summary/` of a project of N cases (tables by case and by site, map, cohort figures, exports, report, `README.md`), regenerated from the run directories |
| `dispatch/` | the adapters that need `Project` and that lower layers must not import: `workflow.py` (`DISPATCH`, `dispatch_workflow`, one `run_*` per workflow, `completed_identical_run` read from the manifests), `rerun.py` (`rerun_config`, `ProjectRerunProvider`) |

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
which import it inside a function.

## Tree

```
hydromodpy/project/
  __init__.py       Project, ProjectRunner, ProjectCatalog, the two accessors
  facade.py  state.py  phases.py  runner.py  run_overrides.py  replay_checks.py
  attempt.py  catalog.py  accessors.py
  spinup.py  lockfile.py  summary.py
  dispatch/         workflow.py  rerun.py
  launch/           local.py  prepare.py  lease.py  journal.py  children.py  env.py
                    status.py  slurm.py  templates/
```

## How a run goes through it

1. **Construct.** `Project(config)` validates the configuration (a TOML path,
   a `HydroModPyConfig`, a dict or a JSON string) through `phases.configure`.
   Nothing heavy runs.
2. **Build the model once.** The first `simulate`, `prepare` or runtime
   accessor calls `_ensure_model_built`: `build_geographic`, `load_data`,
   `build_mesh`. The per-phase verbs do the same one phase at a time.
3. **Execute.** `execute(name=..., **overrides)` is the worker verb. It claims
   `runs/<name>/` through `run_attempt` (a completed name gets `.vN`, a failed
   or aborted one continues as the next attempt, a running one with a fresh
   pulse is refused, `fresh` moves everything aside, `force` takes a stale
   claim), builds the workflow `Pipeline` over `standard_steps()` and returns
   a `SealedRun`. It never opens the index. `from_step`, `until_step`,
   `resume`, `dry_run` and `frozen` act on the step window of that pipeline.
   A run stopped before `setup_process` builds no model; a window ended by
   `until_step` leaves the outcome `partial`.
4. **Simulate.** `simulate(...)` is `execute` followed by `index_new_runs`
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

A file that declares `[sites]` goes through `launch/` instead: `run_plan`
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
| a way an attempt ends | a status of `Outcome` (`results/outcome.py`) and its branch in `attempt.run_attempt` |
| a workflow name | a `run_*` function and an entry in `DISPATCH` in `dispatch/workflow.py`; the name list itself lives in `hydromodpy/workflow/dispatch.py` |
| a provider for a lower layer | a class in `dispatch/`, a Protocol and a `register_*` function in the lower layer, a hook in `hydromodpy/_bootstrap.py` |
| runtime state on `Project` | a field of `ProjectState` and its name in `PROJECT_ATTR_TO_STATE_FIELD` |
