# simulation/execution

How a plan runs.

`runner.py` is `SimulationRunner.execute`: it walks the plan, opens and closes each block of one process type, hands each run to the adapter of its solver, and keeps each model for the runs that depend on it. `ensure_flow`, `ensure_transport` and `ensure_process_context` build the process objects a block needs. The adapter is found through the solver registry provider, so this folder never imports `solver`.
