"""End-to-end: run a toy calibration through the public engine.

The evaluator is a closure over a convex quadratic so we can assert on
the best-so-far value and on the number of iterations recorded in the
``CalibrationSession`` history. No MODFLOW is invoked.
"""

from __future__ import annotations

from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def test_calibration_engine_runs_grid_and_finds_best() -> None:
    space = ParameterSpace(
        [
            CalibParameter(name="x", lower=-1.0, upper=1.0),
            CalibParameter(name="y", lower=-1.0, upper=1.0),
        ]
    )

    optimizer = build_optimizer("grid", space, points_per_dim=3)

    def evaluator(suggestion: ParamSuggestion) -> EvaluationResult:
        x = float(suggestion.values["x"])
        y = float(suggestion.values["y"])
        # Convex quadratic centred on (0, 0).
        objective = x**2 + y**2
        return EvaluationResult(
            trial_id=suggestion.trial_id,
            sim_id=None,
            objective_value=objective,
            status="completed",
        )

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=evaluator,
        max_iter=9,  # 3×3 grid -> 9 evaluations
    )
    session = engine.run()

    assert len(session.history) == 9
    assert session.best is not None
    best_values = session.history[-1]  # last observed
    assert session.best.objective_value <= best_values.objective_value + 1e-9
    # The grid includes (0, 0), so the minimum is exactly 0.
    assert abs(session.best.objective_value) < 1e-12
