# `hydromodpy/simulation`

From the `[simulation]` table to a solved run and the outputs read back from it.
The table lists processes (a mesh, a flow, a transport) and the solvers each one
runs. This package turns that list into an ordered plan, walks the plan one run
at a time, hands each run to the adapter of its solver, and afterwards reads the
solver files into the results store. It knows no solver: the solver registry
is reached through a provider that the root bootstrap wires.
This file is the map of the package: what each part answers, the import rules,
how a plan becomes a run and then results, and where to add what.

## Parts

| part | answers |
|---|---|
| `planning/config.py` | what the modeller wrote: `SimulationConfig` (`[simulation]`), `SimulationTimeConfig` (`[simulation.time]`), and one process model per type, `FlowProcessConfig`, `TransportProcessConfig`, `MeshProcessConfig` |
| `planning/results_config.py`, `planning/observation_config.py` | `[simulation.results]` (what is persisted and kept) and `[observation]` (the points a run samples while it still holds its outputs) |
| `planning/plan.py` | the frozen objects shared by planner, runner and adapters: `ProcessRun`, `SimulationPlan`, `RunContext`, `RunExecutionResult` |
| `planning/planner.py` | `SimulationPlanner.build`: one `ProcessRun` per process and solver, in the order declared, each bound to the earlier run it depends on |
| `execution/runner.py` | `SimulationRunner.execute`: when each run executes, which process-family blocks open and close, where each model is kept; `ensure_flow`, `ensure_transport` and `ensure_process_context` build the process objects a block needs |
| `adapters/` | what the transport adapters of every solver share (`transport_helpers.py`); the solver adapters themselves live in `solver/<backend>/adapters/` |
| `extraction/post_run.py` | what happens after a solve: extract the solver files, derive outputs, export, clean up the scratch folder |
| `extraction/derivation/` | what is computed from stored fields: `catchment_aggregation.py`, `observation_ingest.py`, `fit_metrics.py`, and the output-adapter Protocol in `base.py` |
| `extraction/calibration_bridge.py` | the in-memory path a lumped model takes in a calibration: `make_hot_simulator`, `promote_trial`, `persist_calibration_summary_to_store` |
| `soil_recharge.py` | the soil reservoir run on loaded forcings: precipitation and ETP grids in, recharge, residual ETP and runoff records out, with the printed water-budget block |
| `spinup_config.py` | `SpinupConfig` (`[spinup]`): the settings of the cyclic spin-up. The driver is `project/spinup.py` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives simulation `core`, `schema`,
`physics`, `spatial`, `data` and itself. Today it imports `core`, `physics`,
`spatial`, and `data` once (`soil_recharge.py` reads `data.contracts`). No
`simulation_layout.yaml` orders the parts. The shape is:

1. `planning/` is the lowest part. `execution/`, `adapters/` and `extraction/`
   import it, and `__init__.py` names what they export.
2. Simulation never imports `solver`. It asks
   `core.contracts.solver_registry.get_solver_registry_provider()` for a solver
   adapter (`get_solver_adapter`), an output extractor (`get_extractor_instance`)
   and the bindings a solver requires (`required_bindings`).
   `hydromodpy/_bootstrap.py` sets the provider. `solver` may import
   `simulation`; that is the direction of the edge.
3. A run reaches its adapter through the registry key `(process_type, solver)`.
   The planner binds a dependency only to a run declared earlier in the file.
   A file that lists `transport` before a flow it needs is refused, never
   reordered.

Who imports simulation: `workflow` (most), `solver`, `calibration`, `config`,
`project` and the package root.

## Tree

```
hydromodpy/simulation/
  __init__.py       lazy names: SimulationConfig, SimulationPlan, ProcessRun, RunContext, ...
  planning/         config.py  results_config.py  observation_config.py  plan.py  planner.py
  execution/        runner.py
  adapters/         transport_helpers.py
  extraction/       post_run.py  calibration_bridge.py
    derivation/     base.py  catchment_aggregation.py  observation_ingest.py  fit_metrics.py
  soil_recharge.py  spinup_config.py
```

`extraction/ARCHITECTURE.md` is an older note of the results store and does
not describe the code of this package; `results/README.md` and
`docs/source/contribute/architecture/storage-layout.rst` do.

## How a plan becomes a run

1. **Plan.** `workflow/steps/planning.py` (and `workflow/steps/prepare_solver/`) calls
   `SimulationPlanner.build` on the `SimulationConfig`. A process entry with several solvers expands into one run
   per solver. A mesh process has a `backend` and no solver. The plan is
   immutable.
   A run id is `<process_id>::<solver>`, for example `flow_main::modflow_nwt`.
2. **Bind data.** The workflow's data step puts the loaded data into the `Flow`
   (see `physics/README.md`). `soil_recharge.py` produces the recharge when
   `[flow.sinks_sources.recharge.soil]` is set.
3. **Execute.** The `run_solver` step of the workflow calls
   `SimulationRunner.execute(plan, ctx, callbacks=..., store=...)`. For each
   contiguous block of one `process_type` the runner calls
   `ensure_process_context`, then `before_process`, then each run through the
   adapter of its solver, then `after_process`. An adapter returns a
   `RunExecutionResult`; the runner keeps `primary_model` in
   `models_by_run_id` so a run that lists it in `depends_on` finds it.
4. **Extract.** After the solve, separate workflow steps call
   `extract_run_outputs` (solver files into the store through the extractor of
   the solver), `derive_run_outputs` (catchment aggregates, the
   declared `[observation]` points, the fit metrics against observations
   ingested beside the run), and the export functions of `post_run.py`.
   `post_run_results` composes the same functions in one call; no module
   outside this package calls it.
5. **Clean.** `cleanup_solver_outputs` removes the scratch files unless the
   results config keeps them.

A calibration drives the same runner without the workflow steps:
`calibration/runners/kept_solves.py` calls `SimulationRunner().execute` for the
trials it may promote.

## Where to add what

| to add | where |
|---|---|
| a process type | a process model in `planning/config.py` joined to `SimulationProcessConfig`, its requirements in the solver registry, an `ensure_*` function and an entry in the two tables of `execution/runner.py` (`_REQUIRED_COMPONENTS_BY_PROCESS`, `_COMPONENT_ENSURERS`) |
| a solver for an existing process | in `solver/`, never here; see `docs/source/contribute/architecture/how-to/add-a-solver.rst` |
| a `[simulation]` or `[simulation.results]` field | the field on its model, with a profile and a description; see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a derived field | a row function in `results/derive/virtual_fields.py`: derived fields are rebuilt on read, never written by a run |
| a fit metric | `write_fit_metrics` in `extraction/derivation/fit_metrics.py` |
| a step after the solve | a function in `extraction/post_run.py` and its call in the matching workflow step (`extract`, `derive` or `export` under `workflow/steps/`) |
| a callback around a run | a field of `ProcessCallbacks` and its call in `SimulationRunner` |
