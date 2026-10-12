"""Record on the run store what a MODFLOW extractor kept of the per-cell budget.

The ``budget/`` group of the store carries the policy the extraction applied
and the terms it kept, so a reader tells a dropped term from a term the model
does not produce without reading the run's config.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hydromodpy.core.budget_terms import BudgetKeep


def record_budget_policy(store: Any, sim_id: str, keep: BudgetKeep, written: Iterable[str]) -> None:
    """Write the ``budget/`` attributes once, at the end of a budget extraction.

    A catalog that writes no field store (``save_zarr = false``) gets nothing,
    like every other field write.
    """
    if not getattr(store, "save_zarr", True):
        return
    sz = store.open_zarr(sim_id)
    try:
        sz.write_budget_policy(keep, written)
    finally:
        sz.close()


__all__ = ["record_budget_policy"]
