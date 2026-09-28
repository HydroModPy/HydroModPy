"""A candidate a parallel simplex solved and did not read is journaled as such.

It is a real solve and stays in the history, but it is not on the path of the
search: the journal marks it, and the progress bar does not count it.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import _build_trial

pytestmark = pytest.mark.unit


def _space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])


def _bowl(sugg: ParamSuggestion) -> EvaluationResult:
    x = float(sugg.values["x"])
    return EvaluationResult(
        trial_id=sugg.trial_id, sim_id=None, objective_value=(x - 0.7) ** 2, status="completed"
    )


def test_unused_candidates_are_marked_in_the_journal_and_not_counted() -> None:
    journal: list[dict] = []
    counted: list[int] = []

    class _Reporter:
        def update(self, trial_id, result) -> None:
            counted.append(trial_id)

        def close(self) -> None:
            pass

    def on_iteration(sugg: ParamSuggestion, result: EvaluationResult) -> None:
        journal.append(_build_trial(sugg, result, "summary").metrics or {})

    engine = CalibrationEngine(
        space=_space(),
        optimizer=ScipyNelderMead(_space(), maxiter=12),
        evaluator=_bowl,
        max_iter=12,
        parallel=4,
        progress=_Reporter(),
        on_iteration=on_iteration,
    )
    session = engine.run()

    unused = [row for row in journal if row.get("speculative_unused") == 1.0]
    assert unused, "a width of 4 speculates, so some candidates go unread"
    assert len(counted) == len(journal) - len(unused)
    assert len(session.history) == len(journal)
