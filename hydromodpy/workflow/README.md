# `hydromodpy/workflow`

The order in which a project is built and run. A file such as `step4_transient.toml`
becomes twelve steps, from validation to export. Each step takes an immutable
`PipelineState`, does its part and returns the next one. A `Pipeline` chains the
steps, records them in a journal in the project catalog, and can resume a run from
the artifacts of the steps already done. The `Project` facade and every workflow
launcher (simulation, calibration, comparison, site selection) call these steps, so
one file always drives one lifecycle.
This file is the map of the package: what each part answers, the import rules,
the twelve steps, and where to add what.

## Parts

| part | answers |
|---|---|
| `steps/` | the twelve canonical steps, one module per concern; each exposes `step_*` functions and a `*Step` class that adapts them to the `Step` protocol |
| `orchestrator.py` | `standard_steps()`, the order of the twelve; `prepare_runtime()`, the model phase (workspace, geographic, data, mesh) in one call |
| `runner.py` | `Pipeline`: runs the steps, writes the journal and the heartbeat, resumes, verifies the resolved manifest |
| `dag.py`, `parallel.py` | the step graph built from `depends_on()` and its cohorts (Kahn sort); the executors that run a cohort and the sweep helper `run_sweep` |
| `internals/` | the primitives: `PipelineState` and the `Step` protocol, `ResolvedRunManifest` (the step blueprint and the config digest), `earliest_affected_step` (which step an override reaches), `DerivedRegistry` (ordered derived fields), the description of what a data load read |
| `tracking/` | `WorkflowJournal` (the `workflow_steps` table of the catalog), `WorkflowEventStream`, `ResumePlanner`, `HeartbeatPulse` |
| `phases.py` | the phase vocabulary that `Project` and `Pipeline` share |
| `launcher_protocol.py` | the `Launcher` Protocol: what drives a plan against a state; `SimulationRunner` is the one in tree |
| `run_catalog.py` | the writable catalog of a run, opened for the span of one caller |
| `pipelines/` | two standalone launchers: `mesh.py` (`MeshCatchmentLauncher`) and `overview.py` (`DataOverviewLauncher`) |
| `dispatch.py` | the workflow names (`KNOWN_WORKFLOWS`) and how a file's `[workflow]` mode is read and checked |
| `site_selection.py`, `site_selection_data.py`, `_site_selection_*.py` | the site-selection workflow: plan, build from observed stations, from generated candidates or from a DEM area, or select from a CSV of delineated catchments |
| `regional_lab_materialization.py` | the shared regional flow stack a regional lab materializes for several catchments |

## The twelve steps

`standard_steps()` returns them in this order. Each declares the step it depends
on, so the graph is a chain and every cohort holds one step.

| step | module | answers |
|---|---|---|
| `validate` | `steps/validate.py` | is the file valid before anything is built |
| `resolve` | `steps/resolve.py` | workspace paths and the `WorkflowContext` |
| `build_geographic` | `steps/setup.py` | the geographic context, the domain and the spatial supports |
| `load_data` | `steps/data.py` | the data of `[data]`, bound to the runtime (`apply_*` of `physics` and `spatial`) |
| `build_mesh` | `steps/mesh.py` | the catchment mesh, or an external one |
| `setup_process` | `steps/setup.py` | the process objects, `Flow` and `Transport` |
| `prepare_solver` | `steps/prepare_solver/` | the simulation plan, the run registered in the catalog, the inputs frozen |
| `run_solver` | `steps/run_solver.py` | the plan, executed by `SimulationRunner` |
| `extract` | `steps/extract.py` | the solver files read into the store, the observations ingested |
| `derive` | `steps/derive.py` | derived fields |
| `display` | `steps/display.py` | the figures of `[display]`, drawn while the intermediate fields still exist |
| `export` | `steps/export.py` | the `[[export]]` requests, then the store sealed |

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
   `launcher_protocol.py` and `run_catalog.py`; `runner.py` imports `dag`,
   `internals`, `parallel` and `tracking`. `internals/` and `tracking/` import
   no step.
3. A step's `reads` and `writes` are exact. `tests/unit/architecture/test_step_payload_keys.py`
   derives both from the source of the step and fails when a declaration and the
   code disagree in either direction. `test_workflow_context_members_have_a_reader.py`
   requires every member of `WorkflowContext` to have a reader.
4. `Step` is a runtime-checkable Protocol of `name` and `run`. `reads`, `writes`
   and `config_sections` are class variables of `_TypedStep`, and
   `earliest_affected_step` reads `config_sections`.

## Tree

```
hydromodpy/workflow/
  orchestrator.py  runner.py  dag.py  parallel.py  phases.py  dispatch.py
  launcher_protocol.py  run_catalog.py
  internals/   state.py  step.py  manifest.py  dependencies.py  derived.py  data_description.py
  tracking/    journal.py  events.py  resume.py  heartbeat.py
  steps/       validate  resolve  setup  data  mesh  prepare_solver/  run_solver  extract  derive
               display  export  planning  calibration
  pipelines/   mesh.py  overview.py
  site_selection.py  site_selection_data.py  _site_selection_*.py  regional_lab_materialization.py
```

## How a run goes through it

1. **Build.** `standard_steps()` makes the twelve steps. `Pipeline(steps, workspace=...)`
   builds the graph from `depends_on()`.
2. **Run.** `Pipeline.run(state, resume_from=..., parallel=...)` takes an initial
   `PipelineState`. Each step is `state.advance(...)` over the shared payload; the
   dominant member is `ctx`, the `WorkflowContext`. A cohort of several steps
   would go through a thread pool; the twelve steps give only single-step cohorts.
3. **Journal.** Each step is recorded in the `workflow_steps` table of the project
   catalog with the hash of its artifacts, and a heartbeat marks a live run.
   `ResolvedRunManifest` records the step blueprint and the config digest under
   `.hmp/checkpoints/<run_id>/resolved_manifest.json`.
4. **Resume.** A step that writes durable artifacts implements `artifacts(state_out)`
   and `rebuild_state(...)`. At resume the runner rebuilds the state of a completed
   step from disk and does not run it again. There is no pickle layer and no
   checkpoint store: resume reads artifacts. See
   `docs/source/contribute/architecture/pipeline_resume.rst`.
5. **Window.** `ProjectRunner.run` bounds the step window with `from_step` and
   `until_step`. A calibration trial skips the shared steps: it asks
   `earliest_affected_step` for the first step an override reaches, from the
   `config_sections` of the steps.

## Where to add what

| to add | where |
|---|---|
| a step | a module in `steps/` with its `step_*` function and `*Step` class, exported by `steps/__init__.py`, placed in `standard_steps()`, with `depends_on`, `reads`, `writes` and `config_sections` |
| a persistent step | `artifacts` and `rebuild_state` on the step, so a resume can skip it |
| a derived field | a computation registered in `internals/derived.py` (`DerivedRegistry`) |
| a way to bind loaded data | a function in `steps/data.py` calling the binder of `physics` or `spatial` |
| a workflow mode | a name in `KNOWN_WORKFLOWS` (`dispatch.py`) and its adapter in `project/dispatch/workflow.py`; see `project/README.md` |
| a standalone launcher | a class in `pipelines/` on the steps it needs |
| a launcher backend | a class that satisfies `Launcher` in `launcher_protocol.py` |
| a key of the shared payload | the key in the `reads` and `writes` of the steps that touch it, in the same commit |
