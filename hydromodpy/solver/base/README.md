# Solver port

The solver port is the contract every flow and transport backend meets, so the runner solves a model and never names a solver. It also holds the plan of a simulation and the runner that walks it, because both sit between the `[simulation]` table and the adapter of a solver. `base` reads `core`, `model`, `catchment` and `results`, never a backend, and the `run_solver` step of the workflow reads it.

## What a backend receives

A flow adapter receives the frozen `Model`, its options (the validated table `[solver.<name>]`, or `None`) and a `RunSlot`. `validate` and `build` take them in that order, and `build` also takes `upstream`, the `SolverRun` objects the plan ran before this one. The slot gives the run folder, the name, the folder of the solver binaries, the stop flag and the names later runs read off this one. The folders and the binaries are facts of the machine, so they stay out of the `Model` and out of the options. A flow adapter reads nothing of the setup, the configuration or the store.

A transport receives the `Model` of its flow, an instance of its own `options` class read from `[transport.<name>]`, and exactly one `SolverRun` in `upstream`, the flow its `requires` names. It works in `upstream[0].output_dir`. The runner refuses any other upstream with a typed error.

## What a backend returns

Each call returns a `SolverRun`, a frozen record of the model, the options, the slot, the solver model, the output folder, the input files, `written`, `solved`, `metrics`, `solve_s` and `initial_state_converged`. `build` makes the solver model in memory. `run` writes the input files unless `written` is set, solves and sets `solved`. `extract(solver_run, store, retention)` writes what the backend lists in `writes`, and `cleanup(solver_run)` removes the scratch files once the results are stored. `rerun(previous, model, slot)` exists if and only if `mutable` is not empty, and it returns `None` when the change needs a build.

## What a backend declares

A backend is a class with the twelve attributes of the `SolverAdapter` Protocol of `adapter_protocol.py`, none with a default: `name` and `process_type` (the key), `accepted_meshes`, `geometry` (`cells` or `raster`), `writes`, `reads`, `supports`, `options`, `category` (`distributed`, `integrated` or `lumped`), `native_step`, `mutable` and `requires`. The five members the runner calls are `validate`, `build`, `run`, `extract` and `cleanup`. `supports` is a word of the closed set of `model/supports.py`, and a trait a backend leaves out is refused when the file is read by `config/cross_checks.py`, with the solvers that honour it. The extractor a backend registers apart answers `OutputAdapter`, with `process_type`, `solver_name` and `extract`.

## How a backend registers

`registry.py` holds two registries on the engine of `core/plugin_registry.py`, `solvers` and `extractors`. A backend is keyed on `<process_type>_<name>`, for example `flow_modflow6`, and an extractor on its `process_type` and `solver_name`. The built-in ones are dotted paths in `_BUILTIN_PATHS`, imported on first lookup. An out-of-tree backend publishes an entry point of the same name in the `hydromodpy.solver` group, and its extractor in `hydromodpy.solver.extractor`. `solvers.register` refuses a class that leaves an attribute out, and names it.

## What is refused

`solver.backend` and the `solvers` of a `[[simulation.process]]` are read by `check_registered_name`, which refuses a name nothing serves with the sentence `solver.backend names 'x', and this installation serves ...`, followed by the entry-point group a third party joins through. An unknown key at lookup raises `SolverInputError`.

## What tests it

`tests/ports/test_solver.py` runs on every key of `solvers.names()`, so an installed backend is held to the port without a line of `tests/` naming it. `tests/unit/architecture/test_run_path.py` holds what an adapter may read.
