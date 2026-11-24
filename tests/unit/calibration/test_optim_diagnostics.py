"""Reports on a calibration trace (`optim.diagnostics`).
Correlation between calibrated parameters, report wording and progress line.
Costs are dimensionless.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.optim import progress_reporter
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.diagnostics import (
    convergence_rate,
    correlated_parameter_pairs,
    iterations_to_dataframe,
    parameter_correlation,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET
from tests.unit.calibration._factories_search import make_space, result_of, run_engine, staircase


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"K": k, "Sy": s, "objective_total": 1.0} for k, s in pairs]


def test_short_trace_has_no_pair() -> None:
    assert correlated_parameter_pairs(_trace([(1.0, 2.0)]), threshold=0.8) == []
    assert correlated_parameter_pairs([], threshold=0.8) == []


def test_constant_column_has_no_pair() -> None:
    trace = [{"K": x, "Sy": 0.2, "n": 3.0 * x, "cost": 1.0} for x in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)]

    pairs = correlated_parameter_pairs(trace, ["K", "Sy", "n"], threshold=0.0)

    assert [(first, second) for first, second, _ in pairs] == [("K", "n")]


def test_dataframe_is_copied() -> None:
    src = pd.DataFrame({"trial": [0, 1], "K": [1.0, 2.0], "cost": [0.5, 0.3]})
    df = iterations_to_dataframe(src)
    assert df is not src  # copied
    assert list(df.columns) == ["trial", "K", "cost"]


def test_decreasing_cost_slope() -> None:
    # Objective strictly decreasing: best[0]-best[i] = i, so slope == 1.
    rows = [{"trial": i, "cost": 10.0 - i, "parameters": {}} for i in range(10)]
    out = convergence_rate(rows)
    assert out["n_points"] == 10.0
    assert out["slope"] == pytest.approx(1.0, abs=1e-9)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-9)


def test_flat_cost_slope() -> None:
    rows = [{"trial": i, "cost": 3.0, "parameters": {}} for i in range(8)]
    out = convergence_rate(rows)
    assert out["slope"] == pytest.approx(0.0, abs=1e-12)
    # ss_tot == 0 → NaN R^2 by construction.
    assert np.isnan(out["r_squared"])


def test_one_point_has_no_slope() -> None:
    out = convergence_rate([{"trial": 0, "cost": 1.0, "parameters": {}}])
    for key in ("slope", "intercept", "r_squared"):
        assert np.isnan(out[key])
    assert out["n_points"] == 1.0


def test_slope_of_a_dataframe_column() -> None:
    df = pd.DataFrame({"trial": np.arange(5), "score": [5.0, 4.0, 3.0, 2.0, 1.0]})
    out = convergence_rate(df, objective="score")
    assert out["slope"] == pytest.approx(1.0, abs=1e-9)


def test_independent_parameters_uncorrelated() -> None:
    rng = np.random.default_rng(42)
    n = 400
    a = rng.standard_normal(n)
    b = rng.standard_normal(n)  # independent
    rows = [{"trial": i, "parameters": {"K": float(a[i]), "Sy": float(b[i])}} for i in range(n)]
    corr = parameter_correlation(rows)
    assert list(corr.columns) == ["K", "Sy"]
    assert corr.loc["K", "K"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["Sy", "Sy"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["K", "Sy"] == pytest.approx(corr.loc["Sy", "K"])
    assert abs(corr.loc["K", "Sy"]) < 0.2


def test_linked_parameters_correlate_to_one() -> None:
    rows = [{"trial": i, "parameters": {"K": float(i), "Sy": 2.0 * i + 1.0}} for i in range(50)]
    corr = parameter_correlation(rows)
    assert corr.loc["K", "Sy"] == pytest.approx(1.0, abs=1e-9)


def test_empty_trace_correlation() -> None:
    assert parameter_correlation([]).empty


def test_single_row_correlation_is_nan() -> None:
    rows = [{"trial": 0, "parameters": {"K": 1.0, "Sy": 0.2}}]
    corr = parameter_correlation(rows)
    assert corr.shape == (2, 2)
    assert corr.isna().all().all()


# A root search names its bracket, then the root, never a minimum cost.


ROOT_MIN = 3.0e-6
ROOT_MAX = 2.0e-4


class _Handle:
    def __init__(self, description: str) -> None:
        self.descriptions = [description]

    def update(self, *, description: str | None = None, **_: object) -> None:
        if description is not None:
            self.descriptions.append(description)

    def advance(self, step: float = 1.0) -> None:
        del step


@pytest.fixture
def handles(monkeypatch) -> list[_Handle]:
    seen: list[_Handle] = []

    @contextmanager
    def _task(description: str, *, total: float | None = None, unit: str = "it"):
        del total, unit
        handle = _Handle(description)
        seen.append(handle)
        yield handle

    monkeypatch.setattr(progress_reporter, "progress", SimpleNamespace(task=_task))
    return seen


def _space() -> ParameterSpace:
    return make_space(("K", 1e-7, 1e-3, "log"))


def _two_bounds(sugg: ParamSuggestion) -> EvaluationResult:
    # The cost is lowest far from the combined root, as on the Nancon.
    value = float(sugg.values["K"])
    j_min = staircase(ROOT_MIN, value, 200.0)
    j_max = staircase(ROOT_MAX, value, 200.0)
    return result_of(
        sugg,
        0.5 * abs(j_min) + 0.5 * abs(j_max),
        components={
            "net.n_bounds_scored": 2.0,
            "net.weight_minimal": 0.5,
            "net.weight_maximal": 0.5,
            "net.J_signed_minimal": j_min,
            "net.J_signed_maximal": j_max,
        },
    )


def _search(adapter: BisectionAdapter, evaluator, reporter):
    return run_engine(adapter.space, adapter, evaluator, AUTO_BUDGET, progress=reporter)


def test_two_root_search_ends_on_its_root(handles) -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01, roots=2)
    values: dict[int, float] = {}

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        values[sugg.trial_id] = float(sugg.values["K"])
        return _two_bounds(sugg)

    reporter = ConsoleProgressReporter(
        "bisection", adapter.counted_budget.worst, label=adapter.progress_label
    )
    session = _search(adapter, evaluate, reporter)

    descriptions = handles[0].descriptions
    assert descriptions[0] == "Calibrating (bisection) - bracketing K"
    assert all("best " not in text for text in descriptions)
    assert any("minimal root K in [" in text for text in descriptions)
    assert (
        descriptions[-1]
        == f"Calibrating (bisection) - root K = {values[session.best.trial_id]:.4g}"
    )


def test_closed_reporter_stays_closed(handles) -> None:
    reporter = ConsoleProgressReporter("grid", 2)
    reporter.update(1, EvaluationResult(trial_id=1, sim_id=None, cost=0.5, status="completed"))
    reporter.refresh()
    reporter.close()
    reporter.close()
    drawn = list(handles[0].descriptions)
    reporter.refresh()

    assert handles[0].descriptions == drawn
    assert drawn[-1] == "Calibrating (grid) - best 0.5"


def _ridge_cloud(n: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """A unit square whose cost grows with the distance to the line y = x."""
    rng = np.random.default_rng(0)
    points = rng.uniform(size=(n, 2))
    return points, np.abs(points[:, 1] - points[:, 0])


def test_the_best_fifth_of_a_ridge_is_correlated_and_flat_across_it() -> None:
    from hydromodpy.calibration.optim.diagnostics import best_fifth_ridge

    points, costs = _ridge_cloud()
    found = best_fifth_ridge(points, costs, ["K", "Sy"])
    assert found["n_points"] == 20 and found["n_trials"] == 100
    assert found["spearman"][0][:2] == ("K", "Sy") and found["spearman"][0][2] > 0.9
    assert found["axis_ratio"] > 5.0


def test_the_best_fifth_of_a_round_bowl_has_no_ridge() -> None:
    from hydromodpy.calibration.optim.diagnostics import best_fifth_ridge

    points, _ = _ridge_cloud(400)
    found = best_fifth_ridge(points, np.hypot(*(points - 0.5).T), ["K", "Sy"])
    assert abs(found["spearman"][0][2]) < 0.5 and found["axis_ratio"] < 1.6


def test_the_ridge_needs_five_points_two_parameters_and_finite_values() -> None:
    from hydromodpy.calibration.optim.diagnostics import best_fifth_ridge

    points, costs = _ridge_cloud(4)
    assert best_fifth_ridge(points, costs, ["K", "Sy"]) is None
    points, costs = _ridge_cloud(30)
    assert best_fifth_ridge(points[:, :1], costs, ["K"]) is None
    assert best_fifth_ridge(points, np.full(30, np.nan), ["K", "Sy"]) is None
    flat = np.column_stack([points[:, 0], np.full(30, 0.3)])
    found = best_fifth_ridge(flat, costs, ["K", "Sy"])
    assert "axis_ratio" not in found and found["spearman"] == []


def test_a_lhs_phase_reports_its_ridge_in_search_space_and_a_bobyqa_phase_does_not() -> None:
    from hydromodpy.calibration.runners import search

    space = make_space(("K", 1e-7, 1e-3, "log"), ("Sy", 0.01, 0.3))
    points, costs = _ridge_cloud(50)
    values = {
        i: {"K": 10 ** (-7 + 4 * x), "Sy": 0.01 + 0.29 * y} for i, (x, y) in enumerate(points)
    }
    history = [SimpleNamespace(trial_id=i, cost=float(c)) for i, c in enumerate(costs)]
    session = SimpleNamespace(history=history)
    found = search._fixed_plan_ridge(SimpleNamespace(method="lhs"), space, session, values)
    assert found["n_points"] == 10 and found["axis_ratio"] > 5.0
    assert search._fixed_plan_ridge(SimpleNamespace(method="cma"), space, session, values) is None


def test_the_ridge_gives_no_axis_ratio_with_as_many_points_as_parameters() -> None:
    from hydromodpy.calibration.optim.diagnostics import best_fifth_ridge

    rng = np.random.default_rng(0)
    names = ["a", "b", "c", "d", "e", "f"]
    points, costs = rng.random((25, 6)), rng.random(25)
    # The best fifth is five points, fewer than the six parameters.
    found = best_fifth_ridge(points, costs, names)
    assert found is not None and found["n_points"] == 5
    assert "axis_ratio" not in found


def test_the_ridge_floor_is_relative_to_the_largest_eigenvalue() -> None:
    from hydromodpy.calibration.optim.diagnostics import best_fifth_ridge

    rng = np.random.default_rng(1)
    first = rng.random(40) * 1e6
    flat = np.column_stack([first, first * 2.0 + rng.random(40) * 1e-9])
    found = best_fifth_ridge(flat, rng.random(40), ["a", "b"])
    assert found is not None and "axis_ratio" not in found
