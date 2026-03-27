# Simulation Pipeline

The simulation package separates four responsibilities:

- `SimulationPlanner`: turns the declarative `[simulation]` TOML block into an explicit ordered `SimulationPlan`.
- `SimulationRunner`: walks through that plan, materializes process context when needed via free functions, manages process-family transitions, resolves runtime dependencies, and records outputs.
- `SolverAdapter`: translates one generic `ProcessRun` into the concrete API call sequence for a specific solver.
- Solver classes (`Modflow`, `Modpath`, `Mt3dms`, `Modflow6`, ...): perform the actual numerical or post-processing work.
- Runtime state models (`simulation/state/`): hold setup/data/execution scopes shared by launchers, runner, and postprocess.

The intended pipeline is:

```text
SimulationConfig
-> SimulationPlanner
-> SimulationPlan (ProcessRun...)
-> SimulationRunner
-> ensure_process_context() (on process-family transitions)
-> SolverAdapter
-> Solver implementation
```

A short reading guide:

- `planner` answers: "what should run, and in which order?"
- `runner` answers: "when does each run execute, and what state is carried forward?"
- `ensure_process_context()` answers: "how do we get `flow`/`transport` objects when a block starts?"
- `adapter` answers: "how do I call this concrete solver for this run?"
- `solver` answers: "how does the numerical backend actually compute?"

## Why this separation exists

- Planning rules change when orchestration logic changes.
- Running logic changes when dependency handling or process callbacks change.
- Context materialization changes when process object creation policy changes.
- Adapters change when solver APIs change.
- Solver implementations change when the numerical backend itself changes.

Keeping those concerns separate prevents one kind of change from forcing a rewrite of every layer.

## What the runner should know

`SimulationRunner` should know:

- the ordered list of runs to execute;
- when to ensure process-level context objects exist before callbacks;
- when a process-family block starts or ends;
- how to resolve `depends_on` against `models_by_run_id`;
- how to store the model produced by a completed run.

Put differently: the runner owns execution flow, not solver mechanics.

`SimulationRunner` should not know:

- how to instantiate `Modflow`, `Modpath`, `Mt3dms`, or any other concrete solver;
- which solver-specific options are required to run those classes;
- the exact pre-processing / processing / post-processing call sequence of each solver.

That solver-specific knowledge belongs in `simulation/adapters/`, with one
adapter module per solver grouped under the `flow/` and `transport/` families.

## Where to look in the code

- Planning logic: `simulation/planning/`
- Generic orchestration: `simulation/runtime/runner.py`
- Runtime contracts (`RunContext`, `RunExecutionResult`): `simulation/planning/plan.py`
- Process-context materialization (free functions): `simulation/runtime/runner.py`
- Workspace setup and contracts: `simulation/workspace/`
- Solver-specific bridging code: `simulation/adapters/` (`flow/` and `transport/`)
- Runtime state contracts and concrete models: `simulation/state/`

## Callbacks and adapters

Process-family callbacks are orthogonal to this separation.

- Callbacks can trigger orchestration side-effects around process families.
- Adapters execute one concrete solver for one resolved run.

Keeping callbacks does not require the runner to import solver classes directly.
