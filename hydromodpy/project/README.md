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
| `facade.py` | the public verbs of `Project`: `prepare`, `simulate`, `calibrate`, `spinup`, `rerun`, the model-phase verbs, the launch verbs of a `[sites]` project (`plan`, `launch`, `status`, `collect`, `publish`), the read-only views, `close`; `_execute`, the worker verb of `hmp run`. After the class, the ways to open one: `open_project` (what `hmp.open` calls on a project folder), `configure_opened` (its `project.toml`, read on the first model verb) and `resolve_config` (the polymorphic config input). `Project(config, base=)` loads a path, a mapping, JSON text or a built configuration through `config/loading.load`, and a mapping needs `base` |
| `request.py` | what is a run, before it plays? `RunRequest`, one frozen model of the schema `hydromodpy.request.v1` for a TOML file, a Python call, a JSON file, a server and Docker. It holds the document under `config`, the dotted `set` changes, the overlay names and the options of `hmp run`, and holds neither the base of the relative paths nor the `Environment`. `request_of(source, ...)` builds it from a `.toml` file (chain and overlays read once), a `.json` request, a mapping, JSON text or a built configuration, and refuses the combinations of options a workflow cannot honour. `base_of(source, base)` gives the folder relative paths are read from, and refuses a mapping without one. `RunOutcome` is the typed reading of the `outcome.json` of a finished run, with `identical_to` when a run was given back. The request id and the solution key of a case are told by `workflow/solution_key.py`, which `launch/` reads too |
| `calibrate.py` | the routing behind `Project.calibrate` and `hmp.calibrate` on a path: a TOML file to the staged or the CLI runner (`calibrate_a_file`), a declaration held in memory (`parameters=`, `protocol=`, the `[calibration]` of the project) to the programmatic runner (`calibrate_project`) |
| `trial_pipeline.py` | `WorkflowTrialPipeline`, the implementation of the `TrialPipeline` protocol of `calibration/runners/trial.py`, and `fill_trial_pipeline`, which installs it once. The methods import the workflow and the configuration in their bodies, so filling costs almost nothing |
| `state.py` | where the runtime state of a `Project` lives (`ProjectState`), and which attribute names `Project` forwards to it (`PROJECT_ATTR_TO_STATE_FIELD`) |
| `environment.py` | the `Environment` of one verb call, its credentials file and its bounds. A verb that launches, downloads or delivers receives an `Environment`, built by the command line or the server, and the library reads no environment variable for it. The object says where and with what rights a call plays, so it never enters `request.json` or a seal, and `check` reads the credentials file once at the opening of the project |
| `credentials.py` | the reader of `credentials.toml`, which lives outside every project and workspace, with one `[[host]]` block per address prefix and a password written in clear or read from a file; a block answers a destination by its longest matching prefix |
| `phases.py` | the model-phase verbs as free functions: `configure`, `setup_workspace`, `build_geographic`, `load_data`, `reload_data`, `rebuild_geographic`, `build_mesh`, `open_catalog` (the index, read only, and only when it exists) |
| `runner.py` | `ProjectRunner`: one run through the workflow `Pipeline` (step window, resume, overrides, run naming; the attempt protocol `run_attempt` and `SealedRun` live in `workflow/record/attempt.py`, the replay checks in `workflow/replay_checks.py`); `execute` is the worker verb, `run` adds the index and the `Run` view, `draft` says what a run would do |
| `run_overrides.py` | the `set=` of `simulate` as dotted changes of the configuration of the run, the names of `hmp config targets` |
| `accessors.py` | the read-only views `project.data` (`ProjectDataAccessor`) and `project.runs` (`ProjectRunsAccessor`), `ProjectCatalog` (the index binding of a project: `store`, `data`, `runs`, and its `close`), the campaign reads behind `project.cases`, `.sites`, `.best_runs` and `.sessions` (`ProjectSessions`), and `Workspace`, what `hmp.open` returns on a workspace root; the index itself is `project.store`, a `Catalog`, and `project[ref]` is one `Run` |
| `launch/` | the launcher of a `[sites]` project: lease, case selection, prepare, local launch, SLURM array, status, collect into `summary/`, and the plan of a `[sites]` project, `sites/`. See `launch/README.md` |
| `exchange/` | publish a run with its inputs, install a published copy, replay it from its own bytes. See `exchange/README.md` |
| `dispatch/` | the adapters that need `Project` and that lower layers must not import: workflow name to run function, and the rerun of a recorded run that `hmp catalog rerun` calls. See `dispatch/README.md` |
| `compare.py` | how sealed runs of one site are compared, for `hmp report compare` and `hmp.compare`. Each run is read through the public `Run` API, so a comparison runs no simulation, opens no index and writes into no run. `hmp.compare_pair` reads the index and lives in `results/catalog/facade.py`, beside `Catalog.diff` |
| `examples/` | the shipped examples behind `hmp example`: the catalog, the blob cache, the install into a workspace and the rows the command prints. See `examples/README.md` |
| `data_cache.py` | the verbs of `hmp data` that need more than `data`: `lock_data` and `verify_data_lock` (`hmp data lock`, `hmp data lock --check`), `prune_data`, `cited_input_digests`, the sha256 of every file that a run, a kept trial or a lockfile cites, and `pinned_empty_paths`, the empty answers a lockfile pins by their path. `data` prunes and `project` says what is cited, because only `project` reads `data`, `results` and `schema` together. The user files the configurations declare are listed by `config/user_files.py` |
| `api.py` | the public verbs that the facade `hmp` imports from here. `check(source, *, base=None, partial=True, inputs=False, environment=None)` takes a path or a mapping and gives a list of `Diagnostic`. A mapping without `base` gets one `refused_value` diagnostic with the sentence of `load`. On a path it reads the `base_config` chain through `read_document`, expands a `[sites]` project case by case, calls `config.check.check`, and adds the preflight of a calibration when the document has no error and nothing to fill. `hmp config check` calls it with `partial=False` |
| `spinup.py` | `run_spinup`: repeat a forcing window, each cycle restarting from the last, until heads and lake stages stop moving |

## Import rules

`project` sits above the layer matrix, like `cli`. `layer_matrix.yaml` lets it
import every layer, itself included. Today it imports
`calibration`, `config`, `core`, `data`, `display`, `model`, `results`,
`schema`, `solver`, `catchment` and `workflow`. Two rules matter more than the table:

1. No lower layer imports `project`. Only the package root (lazy, a tolerated
   edge in `layer_matrix.yaml`) and `cli` do. A lower layer that needs a
   `Project` declares a Protocol and receives the adapter at start-up.
2. One global crosses to a lower layer: the trial pipeline of
   `calibration/runners/trial.py`, the only one the library keeps. This package
   fills it through `fill_trial_pipeline` of `trial_pipeline.py` at the opening
   of a session, the CLI calls it once at start-up, and a worker process of a
   parallel search receives the dotted path of that function and runs it itself.
   No other adapter is wired through a global: `cli` sits above `project` and
   calls the adapters of `dispatch/` directly.

No `project_layout.yaml` orders the modules inside the package, because the modules import each other
both ways (`facade.py` and `accessors.py`, `runner.py`, `calibrate.py`) and a layout row names only rows above
it. `tests/unit/architecture/test_project_launch_and_exchange_stand_alone.py` holds the one rule that
stays true. The shape is the one `__init__.py` documents: `facade.py` composes `ProjectRunner`,
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
  facade.py         Project and its verbs, open_project
  calibrate.py      routing of Project.calibrate
  trial_pipeline.py the TrialPipeline calibration reads, filled here
  request.py        RunRequest, request_of, base_of, RunOutcome
  state.py  phases.py  runner.py  run_overrides.py  spinup.py
  environment.py  credentials.py
  compare.py        the comparison of sealed runs
  data_cache.py     lock, check and prune of the data cache
  accessors.py      the read-only views and ProjectCatalog
  dispatch/         workflow.py  rerun.py                      (README.md)
  launch/           the [sites] launcher, SLURM and summary/   (README.md)
  exchange/         share.py  install.py  replay.py            (README.md)
  examples/         catalog, blob cache, install, rows         (README.md)
```

## How a run goes through it

1. `Project(config, base=)` validates the configuration (a TOML path, a `HydroModPyConfig`, a
   dict or a JSON string) through `config/loading.load` in `phases.configure`. A dict or a JSON
   string needs `base`. Nothing heavy runs.
2. The first `simulate`, `prepare` or runtime accessor calls `_ensure_model_built`:
   `build_geographic`, `load_data`, `build_mesh`. The per-phase verbs do the same one phase at a
   time.
3. `simulate(...)` builds a `RunRequest` with `request_of` and plays it through the same runner as
   `hmp run`, so a sweep from an open project takes the same claim. The runner loads the
   document, checks the environment and the run name, then claims `runs/<name>/` through
   `run_attempt` (a completed name gets `.vN`, a failed or aborted one continues as the next
   attempt, a running one with a fresh pulse is refused, `fresh` moves everything aside, `force`
   takes a stale claim). It writes `request.json` for a request given as JSON or as a dict and
   `config.toml` for every run, resolves the inputs to files with a digest, and writes the
   `request_id` into `outcome.json`. It builds the workflow `Pipeline` over `standard_steps()`
   and returns a `RunOutcome`. It never opens the index. `from_step`, `until_step`, `resume`
   and `frozen` act on the step window of that pipeline. A run stopped before `setup_process`
   builds no model, and a window ended by `until_step` leaves the outcome `partial`.
4. `simulate` then calls `index_new_runs` and gives the `Run` view of the new directory through
   `Catalog(project_root)`, opened read only.
5. `calibrate` routes to the calibration runners: the phased runner for phases, the programmatic
   runner for keyword arguments, the CLI runner for one search from a file. A calibration given
   as JSON or as a dict loads first and then runs the `[calibration]` it declares.
6. `project.runs` and `project.data` list what the index holds. `Run` objects come from
   `results`. The index is derived from `runs/` and `sessions/` and is never written by a run.
7. `close()` closes the index. `with Project(...) as project` does it.

From a terminal, `hmp run` and `hmp.run` build the request and call
`dispatch.workflow.dispatch_workflow` with the workflow the document declares. `hmp run x.json`
plays a request saved as JSON, and `--base DIR` names the folder relative paths are read from. A
plain run whose `solution_key` equals the key of a sealed run of the same name is not computed:
the claim is withdrawn and that run is given back, and `force` computes anyway. `hmp run` and
`hmp calibrate` skip this way and no other verb does. The CLI indexes the new directory once the
worker has returned.

A file that declares `[sites]` goes through `launch/` instead (details in `launch/README.md`): `run_plan`
takes the lease, writes the plan when the current one is out of date, runs
the prepare phase, then starts one `hmp run plan/<hash>/<case>.toml --frozen`
process per case within the budget of `[sites.run] parallel`, writes the
journal of the launch and indexes each case when it ends.

## Where to add what

| to add | where |
|---|---|
| a public verb on `Project` | a method in `facade.py` that delegates to `runner.py`, `phases.py` or a new module; no business logic in the facade |
| a model-phase verb | a function in `phases.py` and a thin method on `Project` |
| a run option | a member of `RunRequest` and a keyword of `request_of`, then the option on `simulate` and on `hmp run` |
| a way an attempt ends | a status of `Outcome` (`results/outcome.py`) and its branch in `workflow/record/attempt.py` (`run_attempt`) |
| a workflow name | a `run_*` function and an entry in `DISPATCH` in `dispatch/workflow.py`; the name list itself lives in `hydromodpy/workflow/dispatch.py` |
| a launcher step, a scheduler or a `summary/` table | `launch/`, see its README |
| a publish, install or replay step | `exchange/`, see its README |
| a table of `hmp report compare` | one function and one line in `compare` of `compare.py`, and one test in `tests/unit/project/test_compare.py`; nothing is computed that `Run` can answer, and no unit is converted |
| a shipped example | an entry of `WHITELIST` in `examples/generate.py`, then `python -m tools.dev examples manifest` to write `catalog.toml` |
| a way for a lower layer to reach this package | nothing to wire: the layer declares its Protocol and receives the object as an argument. The one exception is the trial pipeline, filled by `trial_pipeline.py` |
| runtime state on `Project` | a field of `ProjectState` and its name in `PROJECT_ATTR_TO_STATE_FIELD` |
