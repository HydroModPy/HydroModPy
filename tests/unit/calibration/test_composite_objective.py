"""Unit tests for composite calibration objectives."""

from __future__ import annotations

import pytest

pytest.skip(
    "legacy analysis/calibration superseded by P09 hydromodpy/calibration",
    allow_module_level=True,
)


import numpy as np
import pytest

from hydromodpy.analysis.calibration.core.composite_objective import (
    CompositeObjective,
    CompositeObjectiveBlock,
)
from hydromodpy.analysis.calibration.core.engine import CalibrationEngine
from hydromodpy.analysis.calibration.core.methods_dispatcher import CalibrationMethod
from hydromodpy.analysis.calibration.core.objective_function import ObjectiveFunction


def test_objective_function_supports_mae_metric():
    """Canonical objective wrapper should expose MAE end-to-end."""
    objective = ObjectiveFunction(metric="mae")
    evaluation = objective.evaluate(
        observed=np.array([1.0, 3.0], dtype=float),
        simulated=np.array([2.0, 2.0], dtype=float),
        return_components=False,
    )

    assert evaluation["metric"] == "mae"
    assert evaluation["value"] == pytest.approx(1.0, abs=1.0e-12, rel=0.0)
    assert objective.value_to_cost(evaluation["value"]) == pytest.approx(
        1.0,
        abs=1.0e-12,
        rel=0.0,
    )


def test_composite_objective_normalizes_weighted_block_costs():
    """Weighted block aggregation should normalize both weights and raw costs."""

    def _simulator(_params):
        return {
            "heads": np.array([11.0, 13.0], dtype=float),
            "flux": np.array([4.0, 6.0], dtype=float),
        }

    objective = CompositeObjective(
        simulator=_simulator,
        blocks=(
            CompositeObjectiveBlock(
                name="heads",
                observed=np.array([10.0, 14.0], dtype=float),
                selector=lambda payload: payload["heads"],
                metric="rmse",
                weight=3.0,
            ),
            CompositeObjectiveBlock(
                name="flux",
                observed=np.array([2.0, 6.0], dtype=float),
                selector=lambda payload: payload["flux"],
                metric="rmse",
                weight=1.0,
            ),
        ),
    )

    evaluation = objective.evaluate({})

    assert evaluation.total_cost == pytest.approx(
        0.5517766952966369,
        abs=1.0e-12,
        rel=0.0,
    )
    assert evaluation.total_score == pytest.approx(
        -0.5517766952966369,
        abs=1.0e-12,
        rel=0.0,
    )
    assert [block.name for block in evaluation.blocks] == ["heads", "flux"]
    assert evaluation.blocks[0].reference_scale == pytest.approx(2.0)
    assert evaluation.blocks[0].normalized_cost == pytest.approx(0.5)
    assert evaluation.blocks[0].weight_normalized == pytest.approx(0.75)
    assert evaluation.blocks[1].reference_scale == pytest.approx(2.0)
    assert evaluation.blocks[1].weight_normalized == pytest.approx(0.25)


def test_calibration_engine_accepts_composite_objective_evaluator():
    """CalibrationEngine should support composite evaluators without 1D observed data."""

    def _simulator(params):
        a = float(params["a"])
        return {
            "heads": np.array([a, a + 1.0], dtype=float),
            "flux": np.array([2.0 * a, 2.0 * a + 2.0], dtype=float),
        }

    objective = CompositeObjective(
        simulator=_simulator,
        blocks=(
            CompositeObjectiveBlock(
                name="heads",
                observed=np.array([1.0, 2.0], dtype=float),
                selector=lambda payload: payload["heads"],
                metric="rmse",
                weight=2.0,
            ),
            CompositeObjectiveBlock(
                name="flux",
                observed=np.array([2.0, 4.0], dtype=float),
                selector=lambda payload: payload["flux"],
                metric="rmse",
                weight=1.0,
            ),
        ),
    )

    def _fake_simplex(objective_cost, bounds, **kwargs):
        _ = bounds, kwargs
        x = np.array([0.5], dtype=float)
        return {
            "method": "simplex",
            "x_best": x,
            "cost_best": float(objective_cost(x)),
            "n_evaluations": 1,
        }

    methods = CalibrationMethod({"simplex": _fake_simplex})
    engine = CalibrationEngine(
        observed=None,
        simulator=None,
        bounds={"a": (0.0, 1.0)},
        objective_metric="kge",
        objective_evaluator=objective,
        calibration_method=methods,
    )

    result = engine.calibrate(method="simplex")

    assert np.isinf(engine.cost(np.array([2.0], dtype=float)))
    payload = engine.simulate(np.array([0.5], dtype=float))
    assert sorted(payload) == ["flux", "heads"]
    assert result.params_best == {"a": 0.5}
    assert result.cost_best == pytest.approx(1.0, abs=1.0e-12, rel=0.0)
    assert result.score_best == pytest.approx(-1.0, abs=1.0e-12, rel=0.0)
    assert "objective_evaluation" in result.metadata
    assert result.metadata["objective_evaluation"]["blocks"][0]["name"] == "heads"
    assert result.metadata["objective_evaluation"]["blocks"][1]["name"] == "flux"
