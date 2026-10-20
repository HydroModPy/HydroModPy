"""``max_iter = "auto"`` sizes a grid to every one of its points.

The grid published no counted budget, so ``"auto"`` gave it the budget of an
engine that cannot count, 100: three parameters on five points each, 125
points, were cut at 100, the last value of the first parameter never visited,
and the session still reported a converged search.
"""

from __future__ import annotations

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import resolve_budget


def _space() -> ParameterSpace:
    return ParameterSpace(
        [CalibParameter(name=name, lower=0.0, upper=1.0) for name in ("a", "b", "c")]
    )


def _evaluate(suggestion):
    return EvaluationResult(
        trial_id=suggestion.trial_id,
        sim_id=None,
        objective_value=float(sum(suggestion.values.values())),
        status="completed",
        metadata={"values": dict(suggestion.values)},
    )


def test_auto_budgets_every_point_of_the_grid() -> None:
    optimizer = build_optimizer("grid", _space(), points_per_dim=5)

    assert resolve_budget(optimizer, "auto") == 125


def test_the_whole_grid_is_visited() -> None:
    space = _space()
    optimizer = build_optimizer("grid", space, points_per_dim=[5, 5, 6])
    session = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=_evaluate, max_iter="auto"
    ).run()

    assert len(session.history) == 150
    assert max(result.metadata["values"]["a"] for result in session.history) == 1.0
