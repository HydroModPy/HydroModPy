"""What a run keeps of its solver outputs, handed to the extractor of each run.

The extract step of the workflow builds one ``Retention`` from
``[simulation.results]`` and the per-cell budget the planning kept, and every
``extract`` and ``cleanup`` of the run reads it. The module is not named
``retention.py`` because ``results/retention.py`` is the collection behind
``hmp catalog gc``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hydromodpy.core.budget.terms import BudgetKeep


@dataclass(frozen=True, slots=True)
class Retention:
    """What one run keeps: the per-cell budget terms, and the raw solver files or not.

    ``budget`` is the ``BudgetKeep`` the planning decided from
    ``keep_per_cell_budget`` and the consumers of the run. The extractor writes
    the per-cell budget terms it keeps and no other. ``solver_files`` is
    ``keep_solver_files``: true keeps the raw solver files of a sealed run,
    false lets the export step call ``cleanup`` once the results are stored.

    The face flows and the final state have no writer yet, so they have no
    member. Each one joins with the code that writes it.
    """

    budget: BudgetKeep
    solver_files: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.budget, BudgetKeep):
            raise TypeError(f"Retention.budget is a BudgetKeep, got {type(self.budget).__name__}.")
        if not isinstance(self.solver_files, bool):
            raise TypeError(
                f"Retention.solver_files is a bool, got {type(self.solver_files).__name__}."
            )

    @classmethod
    def of(cls, results: Any, budget: BudgetKeep) -> Retention:
        """Return what a run keeps, from its ``[simulation.results]`` and its kept budget.

        ``results`` is the ``ResultsConfig`` of the run, read for
        ``keep_solver_files``. ``budget`` is the ``BudgetKeep`` the planning
        derived from ``keep_per_cell_budget``, or the one a resume read back
        from the store.
        """
        return cls(budget=budget, solver_files=bool(results.keep_solver_files))


__all__ = ["Retention"]
