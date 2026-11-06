# `hydromodpy/simulation`

From the `[simulation]` table to a solved run and the outputs read back from it.
The table lists processes (a mesh, a flow, a transport) and the solvers each one
runs. This package turns that list into an ordered plan, walks the plan one run
at a time, hands each run to the adapter of its solver, and afterwards reads the
solver files into the results store. It knows no solver: the solver registry
is reached through a provider that the root bootstrap wires.
This file is the map of the package: what each part answers, the import rules,
how a plan becomes a run and then results, and where to add what. Each folder
has its own `README.md`.

## Parts

| part | answers |
|---|---|
| `planning/config.py` | what the modeller wrote: `SimulationConfig` (`[simulation]`), `SimulationTimeConfig` (`[simulation.time]`), and one process model per type, `FlowProcessConfig`, `TransportProcessConfig`, `MeshProcessConfig` |
| `planning/results_config.py`, `planning/observation_config.py` | `[simulation.results]` (what is persisted and kept) and `[observation]` (the points a run samples while it still holds its outputs) |
| `planning/plan.py` | the frozen objects shared by planner, runner and adapters: `ProcessRun`, `SimulationPlan`, `RunContext`, `RunExecutionResult` |
| `planning/planner.py` | `SimulationPlanner.build`: one `ProcessRun` per process and solver, in the order declared, each bound to the earlier run it depends on |
| `execution/runner.py` | `SimulationRunner.execute`: when each run executes, which process-family blocks open and close, where each model is kept; `ensure_flow`, `ensure_transport` and `ensure_process_context` build the process objects a block needs |
| `transport_runs.py` | what the transport adapters of every solver share; the solver adapters themselves live in `solver/<backend>/adapters/` |
| `post_run.py` | what happens after a solve: extract the solver files, derive outputs, clean up the scratch folder; it also holds `OutputAdapter`, the port a solver extractor follows |
| `catchment_aggregation.py`, `observation_ingest.py` | what is computed from stored fields: the catchment series and the observation points; the scores of a run live in `results/fit_metrics.py` |
| `soil/` | the soil reservoir run on loaded forcings: the precipitation and ETP grids and their guards (`grids.py`), the capacity classes of each cell (`columns.py`), the run and its recharge, residual ETP and runoff fields (`recharge.py`), and the printed water-budget block (`budget.py`) |
| `spinup_config.py` | `SpinupConfig` (`[spinup]`): the settings of the cyclic spin-up. The driver is `project/spinup.py` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives simulation `core`,
`physics`, `spatial` and itself. The soil reads its loaded records through
`physics.contracts` (`LoadResultProto`, `FieldRecordProto`), so it imports no
`data` module. No `simulation_layout.yaml` orders the parts. The shape is:

1. `planning/` is the lowest part. `execution/`, `post_run.py` and
   `transport_runs.py` import it, and `__init__.py` names what they export.
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
  soil/             grids.py  columns.py  recharge.py  budget.py
  post_run.py  catchment_aggregation.py  observation_ingest.py
  transport_runs.py  spinup_config.py
```

## How a plan becomes a run

1. **Plan.** `workflow/steps/planning.py` (and `workflow/steps/prepare_solver/`) calls
   `SimulationPlanner.build` on the `SimulationConfig`. A process entry with several solvers expands into one run
   per solver. A mesh process has a `backend` and no solver. The plan is
   immutable.
   A run id is `<process_id>::<solver>`, for example `flow_main::modflow_nwt`.
2. **Bind data.** The workflow's data step puts the loaded data into the `Flow`
   (see `physics/README.md`). `soil/recharge.py` produces the recharge when
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
   `post_run_results` composes the same functions in one call; the solver
   adapters call it through `solver/modflow_common/flow_adapter_helpers.py`
   and `solver/base/registry.py`.
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
| a fit metric | `fit_metrics` in `hydromodpy/results/fit_metrics.py` |
| a step after the solve | a function in `post_run.py` and its call in the matching workflow step (`extract`, `derive` or `export` under `workflow/steps/`) |
| a callback around a run | a field of `ProcessCallbacks` and its call in `SimulationRunner` |
