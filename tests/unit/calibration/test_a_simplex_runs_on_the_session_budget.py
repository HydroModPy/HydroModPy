"""A Nelder-Mead search with no maxiter of its own spends the session budget.

The adapter used to cap itself at 100 iterations whatever ``max_iter`` said, so
a budget of 250 stopped at 100 with the simplex reporting it had run dry.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-1.0, upper=1.0),
            CalibParameter(name="y", lower=-1.0, upper=1.0),
        ]
    )


def _noise():
    """A cost no simplex can settle on, so only the budget stops the search."""
    rng = np.random.default_rng(5)

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=float(rng.uniform(1.0, 2.0)),
            status="completed",
        )

    return evaluate


def _run(max_iter: int, **options):
    optimizer = build_optimizer(
        "scipy_nelder_mead", _space(), seed=1, xatol=0.0, fatol=0.0, **options
    )
    return CalibrationEngine(
        space=optimizer.space, optimizer=optimizer, evaluator=_noise(), max_iter=max_iter
    ).run()


def test_a_budget_above_one_hundred_is_spent_whole() -> None:
    session = _run(250)

    assert len(session.history) == 250
    assert not session.converged


def test_a_maxiter_written_in_the_file_still_stops_the_simplex() -> None:
    session = _run(250, maxiter=20)

    assert len(session.history) < 250
