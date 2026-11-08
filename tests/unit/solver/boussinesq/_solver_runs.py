"""Solved runs for the tests of the Boussinesq extractor and observables."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.model.model import Model, ModelTime
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from tests._helpers.model_factory import make_model


def solver_run_of(
    output_dir: Path | None,
    *,
    start: object = None,
    model: Model | None = None,
    solver_model: Any = None,
    name: str = "flow_main__boussinesq",
) -> SolverRun:
    """The solved run whose solver wrote into ``output_dir``.

    ``start`` is the first boundary of the time grid of its ``Model``, which the
    extractor reads as the start of the simulation. ``model`` replaces that model.
    """
    if model is None:
        grid = None if start is None else SimpleNamespace(boundaries=(start,), window=None)
        model = make_model(time=ModelTime(grid=grid, regime="steady", first_period_steady=True))
    return SolverRun(
        slot=RunSlot(folder=Path(output_dir or ".").parent, name=name),
        model=model,
        solver_model=solver_model,
        output_dir=output_dir,
        written=output_dir is not None,
        solved=output_dir is not None,
    )


def extract_run(
    store: Any, output_dir: Path, *, budget: BudgetKeep | None = None, start: object = None
) -> None:
    """Extract the run of ``output_dir`` into ``store``, keeping every budget term by default."""
    retention = Retention(budget=BudgetKeep.everything() if budget is None else budget)
    BoussinesqOutputAdapter().extract(solver_run_of(output_dir, start=start), store, retention)
