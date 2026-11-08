# solver/base

What every backend shares, and nothing that is MODFLOW only. It also holds the plan of a simulation and the
runner that walks it, because both sit between the `[simulation]` table and the adapter of a solver.

## Modules

1. `adapter_protocol.py` is the contract a backend meets: the `SolverAdapter` Protocol the runner calls (`validate`, `execute`, `cleanup`, `extract_observables`), `CellLocator`, `MeshReadingAdapter` and `STOP_BEFORE_THE_SOLVE`, which a calibration uses to stop a trial before the solve.
2. `registry.py` pairs a `(process_type, solver_name)` key with an adapter class and an extractor class. The built-in ones are dotted paths imported on first lookup. Out-of-tree backends come from the `hydromodpy.solver` and `hydromodpy.solver.extractor` entry-point groups.
3. `solver_config.py` is the `[solver]` table and its backend union.
4. `simulation_config.py` is what the modeller wrote under `[simulation]`: `SimulationConfig`, `SimulationTimeConfig` (`[simulation.time]`), and one model per process, `FlowProcessConfig` and `TransportProcessConfig`, which share their checks of `solvers` and of the registry, and `MeshProcessConfig`. `results_config.py` is `[simulation.results]`, what a run persists and keeps, and `observation_config.py` is `[observation]`, the points a run samples while it still holds its outputs.
5. `plan.py` holds the frozen objects the planner, the runner and the adapters share: `ProcessRun`, `SimulationPlan`, `RunContext` and `RunExecutionResult`. `planner.py` is `SimulationPlanner.build`: one `ProcessRun` per process and solver, in the order declared, each bound to the earlier run it depends on. A run id is `<process_id>::<solver>`, for example `flow_main::modflow_nwt`. The planner binds a dependency only to a run declared earlier in the file, so a file that lists `transport` before a flow it needs is refused and never reordered.
6. `runner.py` is `SimulationRunner.execute`. It walks the plan, opens and closes each block of one process type (`ensure_process_context`, `before_process`, then each run through the adapter of its solver, then `after_process`), and keeps the primary model of each run for the runs that depend on it. `ensure_flow`, `ensure_transport` and `ensure_process_context` build the process objects a block needs. The adapter is found through the solver registry provider, so the runner imports no backend.
7. `transport_runs.py` is what the transport adapters of every solver share.
8. `protocols.py` holds the structural types the backends annotate with: `DomainLike`, `FlowModelLike`, `TransportLike`.
9. `drain_conductance.py` is the drain arithmetic every backend uses: the conductance of a free seepage face from K, and the discharge band.
10. `observables.py` turns a solver series or field into an `ObservableResult`, and says in three states whether a backend can serve an observable (`ObservableSupport`).
11. `cell_lookup.py` finds the cell under a point on a solver mesh or a cell mesh.
12. `cleanup.py` removes the scratch files of a run.

The mapping of the hydraulic properties on the cells is in `model/properties/property_table.py`, and the head a run starts from is in `model/initial/heads.py`.

`base` imports `core`, `model` and `catchment`, never a backend.
