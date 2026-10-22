"""A grid or a Latin hypercube cut short by its budget is refused before any solve.

Both engines stopped on their budget, so a sweep that ``max_trials`` cut short
closed ``converged`` and a staged calibration froze its best point. A grid cut
short visits only the first slice of its first parameter, and a Latin hypercube
cut short loses the one point per stratum it is drawn for. Both count their
design before the first solve, so the budget is judged against it, by the
engine and by ``hmp config check``, and the search converges on its last point.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.adapters.grid_adapter import GridAdapter
from hydromodpy.calibration.optim.adapters.lhs_adapter import LhsAdapter
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.core.exceptions import OptimizerError

pytestmark = pytest.mark.unit


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1e-7, upper=1e-3, search_space="log"),
            CalibParameter(name="Sy", lower=0.01, upper=0.3),
        ]
    )


def _grid() -> GridAdapter:
    return GridAdapter(_space(), points_per_dim=3)


def _lhs() -> LhsAdapter:
    return LhsAdapter(_space(), n_samples=9, seed=1)


def _search(optimizer, max_trials: int | str, calls: list[int]) -> CalibrationEngine:
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        calls.append(sugg.trial_id)
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=float(sugg.values["Sy"]),
            status="completed",
        )

    return CalibrationEngine(
        space=optimizer.space, optimizer=optimizer, evaluator=evaluate, max_trials=max_trials
    )


@pytest.mark.parametrize("make", [_grid, _lhs])
def test_a_budget_below_the_design_is_refused_before_the_first_solve(make) -> None:
    calls: list[int] = []

    with pytest.raises(OptimizerError, match="max_trials = 4 is below the 9 evaluations"):
        _search(make(), 4, calls).run()

    assert calls == []


@pytest.mark.parametrize(
    ("make", "rule"), [(_grid, "every grid point"), (_lhs, "every design point")]
)
@pytest.mark.parametrize("max_trials", [9, 20, "auto"])
def test_a_budget_that_covers_the_design_converges_on_its_last_point(
    make, rule: str, max_trials: int | str
) -> None:
    calls: list[int] = []

    session = _search(make(), max_trials, calls).run()

    assert session.converged
    assert session.stopping_rule == rule
    assert len(calls) == 9


def _config(method: str, max_trials: int | str, options: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": method,
            "max_trials": max_trials,
            "method_options": options,
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
            },
        }
    )


@pytest.mark.parametrize(
    ("method", "options"),
    [
        ("grid", {"points_per_dim": 3}),
        ("grid", {"points_per_dim": [3, 3]}),
        ("lhs", {"n_samples": 9}),
    ],
)
def test_the_preflight_refuses_a_budget_below_the_design(method: str, options: dict) -> None:
    findings = _check_the_budgets(_config(method, 4, options))

    assert [finding.severity for finding in findings] == ["error"]
    assert "max_trials = 4 is below the 9 evaluations" in findings[0].detail


def test_the_preflight_counts_the_default_grid() -> None:
    (finding,) = _check_the_budgets(_config("grid", 24, {}))

    assert "below the 25 evaluations of this search, one per grid point" in finding.detail


@pytest.mark.parametrize("max_trials", [9, "auto"])
def test_the_preflight_passes_a_budget_that_covers_the_design(max_trials: int | str) -> None:
    assert _check_the_budgets(_config("lhs", max_trials, {"n_samples": 9})) == []
