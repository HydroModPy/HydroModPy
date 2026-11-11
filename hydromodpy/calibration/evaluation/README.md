# Trial evaluator port

An evaluator turns one parameter sample into one cost. The port stops at the cost because the scoring path reads the live workflow context of a trial, which only the pipeline produces, and a port around simulated outputs would take the shape of the one implementation that can produce them. `port.py` holds the Protocol and its value types, and `registry.py` holds `evaluators`.

## What an evaluator receives and returns

`evaluate` receives a `TrialRequest` (`trial_id`, `values`) and returns a `TrialOutcome`, whose cost is always to be minimized, with an optional `profile` of the timed steps and solves of the trial, empty by default. A trial it cannot score comes back with the status `failed` or `crashed` and the reason in `error`, never as an exception, because a search has to walk out of a region it cannot score.

## What an evaluator declares and how it registers

The class carries `evaluator_id`, `needs_prepared_model` and `evaluate`. `needs_prepared_model` is read off the class before anything is built, because a `True` answer sends the caller through `prepare_trials`, the geographic, mesh and data prefix of the pipeline. Two evaluators ship through `_BUILTIN_PATHS`: `hydromodpy_pipeline`, the default a document that names none gets, and `analytic_bowl`. A third party publishes an entry point in the `hydromodpy.calibration.evaluator` group. `evaluators.create` builds an evaluator and binds only the constructor parameters the class names out of `CONSTRUCTION_OPTIONS`.

## What is refused and what tests it

`calibration.evaluator` is read by `check_registered_name`, which refuses a name nothing serves with the names served and the entry-point group. An unknown key at lookup raises `CalibrationError`. `tests/ports/test_evaluator.py` runs on every evaluator the registry resolves, so an installed one is held to the port without a line of `tests/` naming it.
