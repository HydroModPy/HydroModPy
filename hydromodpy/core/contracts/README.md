# core/contracts

This folder answers: what do two layers agree on when neither may import the other? It holds only
protocols and small state objects, with no behaviour of their own. The concrete classes live in the
layer that owns them, and an instance travels as an argument of the caller.

## Modules

1. `solver_model.py` is `SolverModel`, the little that every solver model shares.
2. `observables.py` names what a solver adapter can read back during a trial (`ObservableRequest`, `ObservableResult`, `ObservableSupport`).
3. `overview.py` is `DataOverviewState`, the state passed between the phases of the data overview.

## What other layers import from it

`solver` (`SolverModel`), `calibration` (`observables`) and `display` (`overview`). The data cache has
no protocol here: it has one implementation, the sidecars of `data/provenance/sidecars.py`.

## Where to add what

- A new protocol between two layers: one module here, and the concrete class in the layer that owns it.
- Real code: never here, in the layer that owns it.

The layer rules are checked by `tests/unit/architecture/`.
