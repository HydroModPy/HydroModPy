# simulation/planning

What the modeller wrote under `[simulation]`, and the plan made from it.

## Modules

1. `config.py` is `SimulationConfig` (`[simulation]`), `SimulationTimeConfig` (`[simulation.time]`), and one model per process: `FlowProcessConfig` and `TransportProcessConfig`, which share their checks of `solvers` and of the registry, and `MeshProcessConfig`.
2. `results_config.py` is `[simulation.results]`, what a run persists and keeps, and `observation_config.py` is `[observation]`, the points a run samples.
3. `plan.py` holds the frozen objects the planner, the runner and the adapters share: `ProcessRun`, `SimulationPlan`, `RunContext`, `RunExecutionResult`.
4. `planner.py` is `SimulationPlanner.build`: one `ProcessRun` per process and solver, in the order declared.
