# core/contracts

This folder answers: what do two layers agree on when neither may import the other? It holds only
protocols, typed ids and small state objects, with no behaviour of their own. Each one is filled in
at bootstrap by the layer that owns the real code.

## Modules

1. `ids.py` has the typed ids `SimId`, `RunId`, `SessionId`, `TrialId` and `StationId`, so a run id cannot be mixed with a station id.
2. `workflow_step.py` is the `WorkflowStep` protocol every pipeline step follows: a stable name and a run method. `ResumableWorkflowStep` adds resuming.
3. `solver_model.py` is `SolverModel`, the little that every solver model shares.
4. `solver_registry.py` is the provider through which `simulation` and `analysis` reach the solvers without importing them (`get_solver_registry_provider`, `set_solver_registry_provider`).
5. `observables.py` names what a solver adapter can read back during a trial (`ObservableRequest`, `ObservableResult`, `ObservableSupport`).
6. `data_cache_backend.py` is the `DataCacheBackend` protocol of the data cache catalog.
7. `overview.py` is `DataOverviewState`, the state passed between the phases of the data overview.

## What other layers import from it

`solver`, `simulation`, `calibration`, `display` and `workflow`. The root `_bootstrap.py` sets the providers.

## Where to add what

- A new shared id: `ids.py`.
- A new protocol between two layers: a new module here, then its wiring in `hydromodpy/_bootstrap.py`.
- Real code: never here, in the layer that owns it.

The layer rules are checked by `tests/unit/architecture/`.
