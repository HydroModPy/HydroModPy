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
| `facade.py` | the public verbs of `Project`: `prepare`, `simulate`, `calibrate`, `spinup`, `rerun`, the model-phase verbs, the read-only views, `close` |
| `state.py` | where the runtime state of a `Project` lives (`ProjectState`), and which attribute names `Project` forwards to it (`PROJECT_ATTR_TO_STATE_FIELD`) |
| `phases.py` | the model-phase verbs as free functions: `configure`, `setup_workspace`, `build_geographic`, `load_data`, `reload_data`, `rebuild_geographic`, `build_mesh`, `open_catalog` |
| `runner.py` | `ProjectRunner`: one run through the workflow `Pipeline` (step window, resume, dry run, overrides, run naming) and `sweep` |
| `catalog.py` | `ProjectCatalog`: the catalog binding of a project (`store`, `data`, `runs`) and its `close` |
| `accessors.py` | the read-only views `project.data` (`ProjectDataAccessor`) and `project.runs` (`ProjectRunsAccessor`) |
| `spinup.py` | `run_spinup`: repeat a forcing window, each cycle restarting from the last, until heads and lake stages stop moving |
| `lockfile.py` | `write_project_lockfile`: the `hydromodpy.lock` a Python-driven run writes |
| `dispatch/` | the adapters that need `Project` and that lower layers must not import: `workflow.py` (`DISPATCH`, `dispatch_workflow`, one `run_*` per workflow), `calibration.py` (`ProjectTrialPromotionProvider`), `rerun.py` (`ProjectRerunProvider`) |

## Import rules

`project` sits above the layer matrix, like `cli`. `layer_matrix.yaml` lets it
import every layer, itself included. Today it imports `analysis`,
`calibration`, `config`, `core`, `data`, `physics`, `results`, `simulation`,
`solver`, `spatial` and `workflow`. Two rules matter more than the table:

1. No lower layer imports `project`. Only the package root (lazy, a tolerated
   edge in `layer_matrix.yaml`) and `cli` do. A lower layer that needs a
   `Project` declares a Protocol and receives the adapter at start-up.
2. The adapters are wired in `hydromodpy/_bootstrap.py`:
   `ProjectTrialPromotionProvider` into the calibration runners,
   `ProjectRerunProvider` into `results.run.rerun_contract`, and
   `ProjectTestbedRunnerProvider` into the analysis testbed. A new adapter
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
  facade.py  state.py  phases.py  runner.py  catalog.py  accessors.py
  spinup.py  lockfile.py
  dispatch/         workflow.py  calibration.py  rerun.py
```

## How a run goes through it

1. **Construct.** `Project(config)` validates the configuration (a TOML path,
   a `HydroModPyConfig`, a dict or a JSON string) through `phases.configure`.
   Nothing heavy runs.
2. **Build the model once.** The first `simulate`, `prepare` or runtime
   accessor calls `_ensure_model_built`: `build_geographic`, `load_data`,
   `build_mesh`. The per-phase verbs do the same one phase at a time.
3. **Run.** `simulate(**overrides)` calls `ProjectRunner.run`, which builds
   the workflow `Pipeline` over `standard_steps()` and returns a `Run`.
   `from_step`, `until_step`, `resume`, `dry_run` and `frozen` act on the step
   window of that pipeline. A run stopped before `setup_process` builds no
   model.
4. **Calibrate.** `calibrate` routes to the calibration runners: the phased
   runner for phases, the programmatic runner for keyword arguments, the CLI
   runner for one search from a file.
5. **Read back.** `project.runs` and `project.data` list what the catalog
   holds; `Run` objects come from `results`.
6. **Close.** `close()` closes the catalog. `with Project(...) as project`
   does it.

From a terminal, `hmp run` and `hmp.run` call `dispatch.workflow.dispatch_workflow`
with the workflow the file declares. `run_simulation` opens a `Project`,
skips a plain run whose resolved config already completed (unless `force`),
and calls `Project.simulate`.

## Where to add what

| to add | where |
|---|---|
| a public verb on `Project` | a method in `facade.py` that delegates to `runner.py`, `phases.py` or a new module; no business logic in the facade |
| a model-phase verb | a function in `phases.py` and a thin method on `Project` |
| a run option | a keyword of `ProjectRunner.run`, and the same keyword on `simulate` and on `dispatch/workflow.run_simulation` |
| a workflow name | a `run_*` function and an entry in `DISPATCH` in `dispatch/workflow.py`; the name list itself lives in `hydromodpy/workflow/dispatch.py` |
| a provider for a lower layer | a class in `dispatch/`, a Protocol and a `register_*` function in the lower layer, a hook in `hydromodpy/_bootstrap.py` |
| runtime state on `Project` | a field of `ProjectState` and its name in `PROJECT_ATTR_TO_STATE_FIELD` |
