"""The trial the root search returns lies inside the bracket it closed.

The residual steps rather than slides, so near the root many trials share one
``abs(J)`` to the last digit. ``min`` returned the first one evaluated, and on
the Nancon that was trial 13, tied with trial 15 and 0.6 % outside the final
bracket. The bracket is where the root is, so the answer is taken inside it.
"""

from __future__ import annotations

import logging
import math

from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

ROOT = 2.09e-4
PLATEAU = 0.05
"""Half-width, in decades, of the band around the root where abs(J) is flat."""


def _space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=1e-7, upper=1e-3, transform="log")])


def _stepped(sugg: ParamSuggestion) -> EvaluationResult:
    """Residual whose magnitude is exactly 2.913 m within PLATEAU decades of the root."""
    gap = math.log10(ROOT) - math.log10(float(sugg.values["K"]))
    magnitude = 2.913 + 1000.0 * max(0.0, abs(gap) - PLATEAU)
    residual = math.copysign(magnitude, gap)
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=abs(residual),
        status="completed",
        components={"net.J_signed": residual},
    )


def _close(
    adapter: BisectionAdapter, evaluate=_stepped
) -> tuple[list[EvaluationResult], dict[int, float]]:
    """Run the search to closure; return its history and log10 K of each trial."""
    history: list[EvaluationResult] = []
    where: dict[int, float] = {}
    for _ in range(100):
        suggestions = adapter.ask(1)
        if not suggestions:
            break
        for sugg in suggestions:
            where[sugg.trial_id] = math.log10(float(sugg.values["K"]))
        results = [evaluate(sugg) for sugg in suggestions]
        history.extend(results)
        adapter.tell(results)
        if adapter.converged():
            break
    return history, where


def _inside(value: float, low: float, high: float) -> bool:
    return low - 1e-12 <= value <= high + 1e-12


def test_a_tie_outside_the_bracket_loses_to_one_inside() -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01, sweep_points=7)
    history, where = _close(adapter)
    low, high = adapter.bracket

    # The situation of the Nancon: the first trial of minimal cost lies outside.
    first_tie = min(history, key=lambda result: result.objective_value)
    assert not _inside(where[first_tie.trial_id], low, high)

    winner = adapter.best()

    assert winner is not None
    assert winner.objective_value == first_tie.objective_value
    assert _inside(where[winner.trial_id], low, high)


def test_a_lower_cost_outside_the_closed_bracket_is_not_the_answer() -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01, sweep_points=7)

    def with_a_lucky_sweep_point(sugg: ParamSuggestion) -> EvaluationResult:
        result = _stepped(sugg)
        if sugg.trial_id == 1:
            # Far below the root, still positive, but the lowest abs(J) of all.
            return EvaluationResult(
                trial_id=result.trial_id,
                sim_id=None,
                objective_value=0.5,
                status="completed",
                components={"net.J_signed": 0.5},
            )
        return result

    _, where = _close(adapter, with_a_lucky_sweep_point)
    low, high = adapter.bracket

    winner = adapter.best()

    assert winner is not None and winner.trial_id != 1
    assert _inside(where[winner.trial_id], low, high)


def test_the_answer_is_outside_only_when_nothing_completed_lies_inside(caplog) -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01, sweep_points=3)
    suggestions = adapter.ask(3)
    residuals = {1: (5.0, "completed"), 2: (3.0, "crashed"), 3: (-3.0, "crashed")}
    adapter.tell(
        [
            EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                objective_value=abs(residuals[sugg.trial_id][0]),
                status=residuals[sugg.trial_id][1],
                components={"net.J_signed": residuals[sugg.trial_id][0]},
            )
            for sugg in suggestions
        ]
    )

    with caplog.at_level(logging.WARNING):
        winner = adapter.best()

    assert winner is not None and winner.trial_id == 1
    assert "No completed trial lies inside the final bracket" in caplog.text


def test_no_bracket_yet_returns_the_lowest_cost() -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01, sweep_points=3)
    (suggestion,) = adapter.ask(1)
    result = _stepped(suggestion)
    adapter.tell([result])

    assert adapter.bracket is None
    assert adapter.best() is result
    assert adapter.bracket_record() is None
