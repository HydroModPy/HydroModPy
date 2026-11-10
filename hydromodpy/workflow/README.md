# `hydromodpy/workflow`

The order in which a project is built and run. A file such as `step4_transient.toml`
becomes thirteen steps, from validation to the seal of the run. Each step takes an
immutable `PipelineState`, does its part and returns the next one. A `Pipeline`
chains the steps, records them in the journal of the run and can resume a run from
the artifacts of the steps already done. The `Project` facade and every workflow
launcher (simulation, calibration) call these steps, so one file always drives one
lifecycle. A run writes its own directory and nothing else: it never opens the
index of the project, and nothing here imports `hydromodpy.project`.

This file is the map of the package. Each sub-folder has its own README with its
modules in call order: `record/` (what a run writes about
itself), `steps/` (the thirteen steps) and
`steps/prepare_solver/` (the step that opens the run).

## Modules at the root

In the order a run meets them.

| module | what it answers |
|---|---|
| `dispatch.py` | which workflow a file runs: the names in `KNOWN_WORKFLOWS`, the declared `[workflow] mode` or the one its sections imply (`infer_workflow`) |
| `window.py` | which steps a run executes: `from_step`, `until_step` and the model phase (`step_window`) |
| `state.py` | `PipelineState`, the immutable object that flows from step to step (`advance`) |
| `step.py` | the `Step` protocol: `name`, `run`, and the class variables `reads`, `writes`, `config_sections` |
| `runner.py` | `Pipeline(steps, workspace=..., run_dir=...)`: runs the steps, writes the journal, names the current step to the heartbeat, resumes, checks the resolved manifest |
| `dag.py` | the step graph built from `depends_on()` and its cohorts (Kahn sort) |
| `parallel.py` | the executors that run one cohort |
| `overview.py` | `DataOverviewLauncher`: the data overview ("identity card" of a watershed) without a solver run |
| `replay_checks.py` | what a replay of a sealed run checks: its inputs, its configuration, its solver binary |
| `solution_key.py` | when are two runs the same: the request id of a case from its written document and the digest and state of its inputs, then its solution key with the code, the solver binaries and the numeric packages, told offline for a plan (`planned_solution_key`) |
| `products.py` | the product store asked once per kind: the table `PRODUCT_KINDS` (mesh, soil) and `ask`, which reads a present product, builds and stores a missing one; the solver step writes the keys into `products.json` |

`replay_checks.py` sits at the root and not in `record/` because it reads
`steps.prepare_solver.resolved`, and `steps` imports `record`. Inside `record/` it
would close a cycle.

## The thirteen steps

`standard_steps()` (`steps/sequence.py`) returns them in this order. Each declares
the step it depends on, so the graph is a chain and every cohort holds one step.
The modules and their helpers are listed in `steps/README.md`.

| step | module | answers |
|---|---|---|
| `validate` | `steps/validate.py` | is the file valid before anything is built |
| `resolve` | `steps/resolve.py` | workspace paths and the `WorkflowContext` |
| `build_geographic` | `steps/setup.py` | the geographic context, the domain and the spatial supports |
| `load_data` | `steps/data.py` | the data of `[data]`, bound to the runtime (the `apply_*` binders of `model`) |
| `build_mesh` | `steps/mesh.py` | the cell mesh of the engine of `[mesh]` |
| `setup_process` | `steps/setup.py` | the process objects, `Flow` and `Transport`; the solver scratch of the attempt |
| `prepare_solver` | `steps/prepare_solver/` | the simulation plan, the run directory bound, the facts of the run, the configuration frozen into `config.toml` and `config.resolved.toml` |
| `run_solver` | `steps/run_solver.py` | the plan, executed by `SimulationRunner` |
| `extract` | `steps/extract.py` | the solver files read into the store of the run, the observations ingested (the shared functions are in `steps/run_outputs.py`) |
| `derive` | `steps/derive.py` | the catchment aggregates, the observation points and the fit metrics |
| `display` | `steps/display.py` | the figures of `[display]`, drawn from the store of the run |
| `export` | `steps/export.py` | the `[[export]]` requests; `step_after_seal` writes the metadata views once the seal exists |
| `seal` | `steps/export.py` | the seal: `simulation.parquet`, `parameters.parquet`, `provenance.json`, `inputs.json`, `manifest.json` last, `README.md`; the outcome and `<run>/.hmp/` belong to the attempt protocol, after the pipeline |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives `workflow` every layer below it,
itself included: `core`, `schema`, `catchment`, `mesh`, `model`, `data`,
`results`, `solver`, `calibration`, `display`, `config` and `workflow`. Rules:

1. No lower layer imports `workflow`. Only `project`, `cli` and the package root
   do. A lower layer that needs a workflow function receives it as an argument:
   calibration reaches these steps through the `TrialPipeline` protocol of
   `calibration/runners/trial.py`, whose implementation lives in
   `project/trial_pipeline.py` and is filled there.
2. Inside the package, `steps/` imports `record`, `state`, `step` and `runner`;
   `runner.py` imports `dag`, `parallel`, `state`, `step` and `record`. `record/`
   imports `state` and `step` and never `steps`. `replay_checks.py` imports
   `steps.prepare_solver.resolved`, which is why it is not in `record/`.
3. A step's `reads` and `writes` are exact. `tests/unit/architecture/test_step_payload_keys.py`
   derives both from the source of the step and fails when a declaration and the
   code disagree in either direction. `test_workflow_context_members_have_a_reader.py`
   requires every member of `WorkflowContext` to have a reader.
4. `Step` is a runtime-checkable Protocol of `name` and `run`. `reads`, `writes`
   and `config_sections` are class variables of each step, and
   `earliest_affected_step` (`steps/dependencies.py`) reads `config_sections`.
5. A step never opens the index of the project (`Catalog`). It writes through
   `run_store(ctx)` into the directory of the run; the index is derived by the
   launcher once the worker has returned (`results.catalog.indexer`).

## Tree

```
hydromodpy/workflow/
  dispatch.py       which workflow a file runs
  window.py         the window of steps of a run
  state.py          PipelineState
  step.py           the Step protocol
  runner.py         Pipeline
  dag.py            the step graph
  parallel.py       cohort executors
  overview.py       the data overview launcher
  replay_checks.py  what a replay checks
  products.py       the product store and the table of products
  record/           what a run writes about itself (README.md)
  steps/            the thirteen steps (README.md)
    prepare_solver/ the step that opens the run (README.md)
```

## How a run goes through it

1. **Claim.** The launcher (`record/attempt.py`) claims the directory of the
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
   around the pipeline (`record/attempt.py`) finds the seal, flips the outcome
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
| a step | see `steps/README.md`, then its name in `core/pipeline_steps.py` |
| something a run records about itself | `record/README.md` |
| a fact of the run | a field of `RunFacts` (`results/storage/run_facts.py`) and the block of the seal it feeds in `results/storage/sealing.py` |
| a derived field | a row of `VIRTUAL_FIELD_ROWS` in `results/derive/virtual_fields.py`: it is rebuilt on read, never written by a step |
| a workflow mode | a name in `KNOWN_WORKFLOWS` (`dispatch.py`) and its adapter in `project/dispatch/workflow.py`; see `project/README.md` |
| a standalone launcher | a class next to `overview.py`, on the steps it needs |
| a check at replay | a function in `replay_checks.py` |
| a key of the shared payload | the key in the `reads` and `writes` of the steps that touch it, in the same commit |
