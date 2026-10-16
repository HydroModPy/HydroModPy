# `hydromodpy/workflow`

The order in which a project is built and run. A file such as `step4_transient.toml`
becomes thirteen steps, from validation to the seal of the run. Each step takes an
immutable `PipelineState`, does its part and returns the next one. A `Pipeline`
chains the steps, records them in the journal of the run and can resume a run from
the artifacts of the steps already done. The `Project` facade and every workflow
launcher (simulation, calibration) call these steps, so
one file always drives one lifecycle. A run writes its own directory and nothing
else: it never opens the index of the project.
This file is the map of the package: what each part answers, the import rules,
the thirteen steps, and where to add what.

## Parts

| part | answers |
|---|---|
| `steps/` | the thirteen canonical steps, one module per concern; each exposes `step_*` functions and a `*Step` class that adapts them to the `Step` protocol |
| `orchestrator.py` | `standard_steps()`, the order of the thirteen; `prepare_runtime()`, the model phase (workspace, geographic, data, mesh) in one call |
| `runner.py` | `Pipeline(steps, workspace=..., run_dir=...)`: runs the steps, writes the journal of the run, names the current step to the heartbeat, resumes, verifies the resolved manifest |
| `dag.py`, `parallel.py` | the step graph built from `depends_on()` and its cohorts (Kahn sort); the executors that run a cohort |
| `internals/` | the primitives: `PipelineState` and the `Step` protocol, `ResolvedRunManifest` (the step blueprint and the config digest), `earliest_affected_step` (which step an override reaches), the description of what a data load read |
| `tracking/` | `WorkflowJournal` (`<run>/.hmp/checkpoints/steps.json`) and `ResumePlanner` |
| `run_store.py` | `run_store(ctx)`: the `RunStore` of the run of `ctx`, opened for the span of one caller; `run_is_persisted(ctx)` |
| `phases.py` | the phase vocabulary that `Project` and `Pipeline` share |
| `launcher_protocol.py` | the `Launcher` Protocol: what drives a plan against a state; `SimulationRunner` is the one in tree |
| `pipelines/` | one standalone launcher: `overview.py` (`DataOverviewLauncher`) |
| `dispatch.py` | the workflow names (`KNOWN_WORKFLOWS`) and how a file's workflow is read: the declared `[workflow] mode`, or the one its sections imply (`infer_workflow`) |

## The thirteen steps

`standard_steps()` returns them in this order. Each declares the step it depends
on, so the graph is a chain and every cohort holds one step.

| step | module | answers |
|---|---|---|
| `validate` | `steps/validate.py` | is the file valid before anything is built |
| `resolve` | `steps/resolve.py` | workspace paths and the `WorkflowContext` |
| `build_geographic` | `steps/setup.py` | the geographic context, the domain and the spatial supports |
| `load_data` | `steps/data.py` | the data of `[data]`, bound to the runtime (`apply_*` of `physics` and `spatial`) |
| `build_mesh` | `steps/mesh.py` | the cell mesh of the engine of `[mesh]` |
| `setup_process` | `steps/setup.py` | the process objects, `Flow` and `Transport`; the solver scratch of the attempt |
| `prepare_solver` | `steps/prepare_solver/` | the simulation plan, the run directory bound (`bind_run_directory`), the facts of the run, the inputs frozen into `config.toml` |
| `run_solver` | `steps/run_solver.py` | the plan, executed by `SimulationRunner` |
| `extract` | `steps/extract.py` | the solver files read into the store of the run, the observations ingested |
| `derive` | `steps/derive.py` | the catchment aggregates, the observation points and the fit metrics |
| `display` | `steps/display.py` | the figures of `[display]`, drawn from the store of the run |
| `export` | `steps/export.py` | the `[[export]]` requests; `step_after_seal` writes the metadata views once the seal exists |
| `seal` | `steps/seal.py` | the seal: `simulation.parquet`, `parameters.parquet`, `provenance.json`, `inputs.json`, `manifest.json` last, `README.md`; the outcome and `<run>/.hmp/` are the attempt protocol's, after the pipeline |

`steps/planning.py` builds the `SimulationPlan`. `steps/calibration.py` renders the
calibration session report and registers the trial pipeline provider that
calibration uses.

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives workflow every layer
below it, itself included. Today it imports `core`, `config`, `physics`, `data`,
`spatial`, `simulation`, `solver`, `calibration`, `results`, `display`,
`analysis` and `reporting`. Rules:

1. No lower layer imports `workflow`. Only `project`, `cli` and the package root
   do. A lower layer that needs a workflow function receives it through a
   provider: calibration reaches the trial pipeline through
   `calibration/runners/contracts.py`, filled by
   `register_default_trial_pipeline_provider`.
2. Inside the package, `steps/` imports `internals/`, `runner.py`, `orchestrator.py`,
   `launcher_protocol.py` and `run_store.py`; `runner.py` imports `dag`,
   `internals`, `parallel` and `tracking`. `internals/` and `tracking/` import
   no step.
3. A step's `reads` and `writes` are exact. `tests/unit/architecture/test_step_payload_keys.py`
   derives both from the source of the step and fails when a declaration and the
   code disagree in either direction. `test_workflow_context_members_have_a_reader.py`
   requires every member of `WorkflowContext` to have a reader.
4. `Step` is a runtime-checkable Protocol of `name` and `run`. `reads`, `writes`
   and `config_sections` are class variables of `_TypedStep`, and
   `earliest_affected_step` reads `config_sections`.
5. A step never opens the index of the project (`Catalog`). It writes through
   `run_store(ctx)` into the directory of the run; the index is derived by the
   launcher once the worker has returned (`results.catalog.indexer`).

## Tree

```
hydromodpy/workflow/
  orchestrator.py  runner.py  dag.py  parallel.py  phases.py  dispatch.py
  launcher_protocol.py  run_store.py
  internals/   state.py  step.py  manifest.py  dependencies.py  data_description.py
  tracking/    journal.py  resume.py
  steps/       validate  resolve  setup  data  mesh  prepare_solver/  run_solver  extract  derive
               display  export  seal  planning  calibration
  pipelines/   overview.py
```

## How a run goes through it

1. **Claim.** The launcher (`project/attempt.py`) claims the directory of the
   case under `runs/` before the first step: `outcome.json` says `running`,
   a heartbeat pulses, the scratch of the attempt is named. The state carries
   `run_dir`.
2. **Build.** `standard_steps()` makes the thirteen steps.
   `Pipeline(steps, workspace=..., run_dir=...)` builds the graph from `depends_on()`.
3. **Run.** `Pipeline.run(state, resume_from=..., parallel=..., heartbeat=...)`
   takes an initial `PipelineState`. Each step is `state.advance(...)` over the
   shared payload; the dominant member is `ctx`, the `WorkflowContext`. A cohort
   of several steps would go through a thread pool; the thirteen steps give only
   single-step cohorts.
4. **Journal.** Each step is recorded in `<run>/.hmp/checkpoints/steps.json`
   with the hash of its artifacts. `ResolvedRunManifest` records the step
   blueprint and the config digest beside it, in `resolved_manifest.json`; the
   facts of the run (`RunFacts`) accumulate in `facts.json` of the same folder.
5. **Resume.** A step that writes durable artifacts implements `artifacts(state_out)`
   and `rebuild_state(...)`. At resume the runner rebuilds the state of a completed
   step from disk and does not run it again. There is no pickle layer and no
   checkpoint store: resume reads artifacts. See
   `docs/source/contribute/architecture/pipeline_resume.rst`.
6. **Seal.** `SealStep` writes the seal from the facts. The pipeline then writes
   the journal row of the seal and its checkpoint, and the attempt protocol
   around the pipeline (`project/attempt.py`) finds the seal, flips the outcome
   to `completed` and removes `<run>/.hmp/`. A run that stops before the seal
   keeps the outcome the attempt protocol wrote (`failed`, `aborted`, or
   `partial` for a window ended by `--until`) and its attempt state.
7. **Window.** `ProjectRunner.execute` bounds the step window with `from_step` and
   `until_step`. A calibration trial skips the shared steps: it asks
   `earliest_affected_step` for the first step an override reaches, from the
   `config_sections` of the steps.

## Where to add what

| to add | where |
|---|---|
| a step | a module in `steps/` with its `step_*` function and `*Step` class, exported by `steps/__init__.py`, placed in `standard_steps()` and in `phases.STANDARD_PIPELINE_PHASES`, with `depends_on`, `reads`, `writes` and `config_sections` |
| a persistent step | `artifacts` and `rebuild_state` on the step, so a resume can skip it |
| a fact of the run | a field of `RunFacts` (`results/storage/run_facts.py`) and the block of the seal it feeds in `results/storage/sealing.py` |
| a derived field | a row of `VIRTUAL_FIELD_ROWS` in `results/derive/virtual_fields.py`: it is rebuilt on read, never written by a step |
| a way to bind loaded data | a function in `steps/data.py` calling the binder of `physics` or `spatial` |
| a workflow mode | a name in `KNOWN_WORKFLOWS` (`dispatch.py`) and its adapter in `project/dispatch/workflow.py`; see `project/README.md` |
| a standalone launcher | a class in `pipelines/` on the steps it needs |
| a launcher backend | a class that satisfies `Launcher` in `launcher_protocol.py` |
| a key of the shared payload | the key in the `reads` and `writes` of the steps that touch it, in the same commit |
