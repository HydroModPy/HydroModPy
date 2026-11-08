# core/contracts

This folder answers: what do two layers agree on when neither may import the other? It holds only
protocols and small state objects, with no behaviour of their own. Each one is filled in
at bootstrap by the layer that owns the real code.

## Modules

1. `solver_model.py` is `SolverModel`, the little that every solver model shares.
2. `observables.py` names what a solver adapter can read back during a trial (`ObservableRequest`, `ObservableResult`, `ObservableSupport`).
3. `data_cache_backend.py` is the `DataCacheBackend` protocol of the data cache catalog.
4. `overview.py` is `DataOverviewState`, the state passed between the phases of the data overview.

## What other layers import from it

`solver`, `workflow`, `calibration` and `display`. The root `_bootstrap.py` fills the ones that need a layer above.

## Where to add what

- A new protocol between two layers: a new module here, then its wiring in `hydromodpy/_bootstrap.py`.
- Real code: never here, in the layer that owns it.

The layer rules are checked by `tests/unit/architecture/`.
