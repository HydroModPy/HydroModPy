# Optimizer port

An optimizer proposes parameter points and ingests the costs of their trials, so the search loop of `engine.py` drives every method the same way. The registry is `optimizers` in `optimizer.py`. The rest of this folder is what the loop shares around the port: the objective, the parameters, the sampling, the stopping rules, the cost cache and the diagnostics.

## What an optimizer receives and returns

`ask` proposes the next parameter points, `tell` ingests the costs of the trials it proposed, `best` returns the best point so far, and `converged` says when the search may stop. A cost is always to be minimized. `suggest_next` stays on the adapters that plan their own points and is not a member of the port.

## What an optimizer declares

The class carries `ask`, `tell`, `best` and `converged`, a `name` attribute that holds the id the registry and the calibration document write, and an `options` attribute, one of the classes of `method_config.py` without a `method` field. The built-in classes are the adapters of `adapters/`.

## How an optimizer registers

Ten methods ship as dotted paths in `_BUILTIN_PATHS`: `bisection`, `cma_es`, `da_mh_gp`, `gp_mapping`, `grid`, `lhs`, `optuna`, `random_search`, `scipy_de` and `scipy_nelder_mead`. Only `da_mh_gp` is not announced, so the docs and the preflight refusals do not print it, though a file that names it still runs. A third-party method publishes an entry point named on its id in the `hydromodpy.calibration.optimizer` group, or calls `optimizers.register(YourClass)`, and the engine loop finds it through `optimizers.get(name)`.

## What is refused and what tests it

`calibration.method`, `calibration.phases.method` and the two methods of `[calibration.protocol]` are read by `check_registered_name`, which refuses a name nothing serves with the names served and the entry-point group. An unknown key at lookup raises `OptimizerError`. `tests/ports/test_optimizer.py` runs one case per id of `optimizers.names()`, an installed method included.
