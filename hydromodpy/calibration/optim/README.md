# `hydromodpy/calibration/optim/optimizer`

The optimizer port: ask, tell, best, converged.

An optimizer proposes parameter points (`ask`) and ingests evaluation results
(`tell`). The members of the port are `ask`, `tell`, `best` and `converged`;
`suggest_next` stays on the adapters that plan their own points and is not a
member. Each adapter declares its option class on `options`, a
`hydromodpy.calibration.optim.method_config` model without a `method` field,
and carries a `name` attribute, which is its id in the registry
(`calibration/optim/optimizer.py`). A class is known to the engine loop
through `optimizers.get(name)`, read off that same attribute.

Ten method classes ship in this build: `bisection`, `cma_es`, `da_mh_gp`,
`gp_mapping`, `grid`, `lhs`, `optuna`, `random_search`, `scipy_de` and
`scipy_nelder_mead`. Only `da_mh_gp` is not announced, so the docs
and the preflight refusals do not print it, though a file that names it still
runs.

A third-party method joins in one of two ways: an entry point in the group
`hydromodpy.calibration.optimizer`, named on the method id, or
`optimizers.register(YourClass)` on the registry in
`hydromodpy.calibration.optim.optimizer`. Its class carries `ask`, `tell`,
`best` and `converged`, an optional `suggest_next`, a `name` attribute
holding the id the registry and the calibration document write, and an
`options` attribute, one of the classes in
`hydromodpy.calibration.optim.method_config`.
