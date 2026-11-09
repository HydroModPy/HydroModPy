# Trial evaluator port

An evaluator turns one parameter sample into one cost. It receives a
`TrialRequest` (`trial_id`, `values`) and returns a `TrialOutcome` whose cost is
always to be minimized, and a trial it cannot score comes back as `failed` or
`crashed` with the reason in `error`, never as an exception, because a search
has to walk out of a region it cannot score. The port stops at the cost because
the scoring path reads the live workflow context of a trial, which only the
pipeline produces today; a port around simulated outputs would have the shape of
the one implementation that can produce them. The registry is `evaluators` in
`registry.py`, on the shared plugin registry: two evaluators ship through
`_BUILTIN_PATHS`, `hydromodpy_pipeline` and `analytic_bowl`, a third party adds
one through the entry-point group
`hydromodpy.calibration.evaluator`, and `hydromodpy_pipeline` is the default a
document that names none gets. `needs_prepared_model` is read off the class
before anything is built, because a `True` answer sends the caller through
`prepare_trials`, the geographic, mesh and data prefix of the pipeline.
`evaluators.create` builds an evaluator, binding only the constructor parameters
the class names out of `CONSTRUCTION_OPTIONS`.
