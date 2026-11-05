# core/budget

This folder answers: what sign does a water-budget flux have, and which budget terms does a run keep? A per-cell
budget flux has one sign for every solver, the one MODFLOW gives it: positive when water enters the aquifer,
negative when it leaves.

## Modules, in the order a caller uses them

1. `flux.py` names the budget keys of drains and releases, fixes the sign, and gives the helpers that stack them (`budget_outflow`, `drain_stack_with_mover`, `find_drain_budget_key`) and the seepage mask.
2. `terms.py` says which per-cell terms a derived field reads (`budget_terms_for`) and which terms a store kept (`BudgetKeep`, `kept_budget`), so a run that dropped the full budget still tells what it can rebuild.

## What other layers import from it

`results` (most of the users), `solver`, `workflow`, `display` and `simulation`.

## Where to add what

- A new drain or release budget key: the tuples in `flux.py`.
- A derived field that needs a new term: the table behind `budget_terms_for` in `terms.py`.
- A solver that writes fluxes: it must write the MODFLOW sign, not convert it later.

The tests are in `tests/unit/`. The layer rules are checked by `tests/unit/architecture/`.
