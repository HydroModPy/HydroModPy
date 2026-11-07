# core/contracts

This folder answers: what do two layers agree on when neither may import the other? It holds only
protocols and small state objects, with no behaviour of their own. Each one is filled in
at bootstrap by the layer that owns the real code.

## Modules

1. `solver_model.py` is `SolverModel`, the little that every solver model shares.
2. `solver_registry.py` is the provider through which the runner of `solver/base` and `analysis` reach the solvers without importing them (`get_solver_registry_provider`, `set_solver_registry_provider`).
3. `observables.py` names what a solver adapter can read back during a trial (`ObservableRequest`, `ObservableResult`, `ObservableSupport`).
4. `data_cache_backend.py` is the `DataCacheBackend` protocol of the data cache catalog.
5. `overview.py` is `DataOverviewState`, the state passed between the phases of the data overview.

## What other layers import from it

`solver`, `workflow`, `calibration` and `display`. The root `_bootstrap.py` sets the providers.

## Where to add what

- A new protocol between two layers: a new module here, then its wiring in `hydromodpy/_bootstrap.py`.
- Real code: never here, in the layer that owns it.

The layer rules are checked by `tests/unit/architecture/`.
