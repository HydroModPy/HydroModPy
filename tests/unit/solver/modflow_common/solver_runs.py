"""Solver runs and retentions for tests that read the output of a solved model.

``solved_run`` is the ``SolverRun`` a finished solve leaves for a folder, and
``keep_all`` the ``Retention`` of a run that keeps every per-cell budget term.
Not public API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import RunSlot, SolverRun

__all__ = ["keep_all", "retention", "solved_run"]


def solved_run(
    directory: Path,
    *,
    options: BaseModel | None = None,
    model: Any = None,
    solver_model: Any = None,
) -> SolverRun:
    """Return the solved, written ``SolverRun`` of a solver that wrote into ``directory``."""
    directory = Path(directory)
    return SolverRun(
        slot=RunSlot(directory.parent, directory.name),
        model=model,
        options=options,
        solver_model=solver_model,
        output_dir=directory,
        written=True,
        solved=True,
    )


def retention(budget: BudgetKeep | None = None, *, solver_files: bool = False) -> Retention:
    """Return a ``Retention`` that keeps ``budget``, every term by default."""
    return Retention(
        level="result",
        budget=BudgetKeep.everything() if budget is None else budget,
        solver_files=solver_files,
    )


keep_all = retention()
