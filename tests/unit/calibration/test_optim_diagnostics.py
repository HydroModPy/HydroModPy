"""Tests of `optim.diagnostics`."""

from __future__ import annotations

import math
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.optim import progress_reporter
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.cost_margin import margin_intervals
from hydromodpy.calibration.optim.diagnostics import (
    convergence_rate,
    correlated_parameter_pairs,
    iterations_to_dataframe,
    parameter_correlation,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET
from hydromodpy.calibration.runners.cli_runner import calibration_trace
from tests.unit.calibration._factories_search import make_space, result_of, run_engine, staircase

# From test_correlated_parameters_are_reported.py
# Two parameters that traded off against each other must be named.
#
# A calibration returns one value per parameter and says nothing about whether the
# data could tell them apart. When K rises and Sy falls across the whole trace to
# keep the same cost, the pair is not identified: the search stopped somewhere on a
# ridge and reported that point as if it were a minimum. That is the equifinality
# the literature on this two-stage protocol leaves open, and the diagnostic for it
# is the correlation between calibrated parameters over the trace.
#
# ``optim/diagnostics.parameter_correlation`` computed that matrix already, from
# the trace ``persistence`` already writes, with a test of its own and no caller.


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"K": k, "Sy": s, "objective_total": 1.0} for k, s in pairs]


def test_a_ridge_is_named_with_its_coefficient() -> None:
    """A perfect trade-off between two parameters is reported."""
    trace = _trace([(1.0, 10.0), (2.0, 9.0), (3.0, 8.0), (4.0, 7.0), (5.0, 6.0), (6.0, 5.0)])

    pairs = correlated_parameter_pairs(trace, threshold=0.8)

    assert len(pairs) == 1
    first, second, coefficient = pairs[0]
    assert {first, second} == {"K", "Sy"}
    assert coefficient < -0.99


def test_independent_parameters_are_not_reported() -> None:
    """The diagnostic stays quiet when the search separated them."""
    trace = _trace([(1.0, 5.0), (2.0, 5.0), (3.0, 5.0), (1.0, 6.0), (2.0, 6.0), (3.0, 6.0)])

    assert correlated_parameter_pairs(trace, threshold=0.8) == []


def test_a_trace_too_short_to_judge_says_nothing() -> None:
    """One point carries no correlation, and inventing one would be worse."""
    assert correlated_parameter_pairs(_trace([(1.0, 2.0)]), threshold=0.8) == []
    assert correlated_parameter_pairs([], threshold=0.8) == []


@pytest.mark.parametrize(
    ("under", "expected"), [(6, [("K", "Sy", 1.0)]), (5, [])], ids=["ridge", "too_few_trials"]
)
def test_the_coefficient_reads_the_trials_under_the_cost(under, expected) -> None:
    # The ridge sits exactly at the limit, which is kept. Costs and values that read as
    # text are no number, and the trials that carry them are left out.
    ridge = [{"K": x, "Sy": 2.0 * x, "cost": 2.0} for x in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)[:under]]
    elsewhere = [{"K": x, "Sy": -5.0 * x, "cost": 9.0} for x in (7.0, 8.0, 9.0)]
    unread = [{"K": 11.0, "Sy": 1.0, "cost": "n/a"}, {"K": "n/a", "Sy": 1.0, "cost": 9.0}]
    trace = [*ridge, *elsewhere, {"K": 10.0, "Sy": 0.0, "cost": None}, *unread]

    assert correlated_parameter_pairs(trace, ["K", "Sy"], below_cost=2.0) == expected
    assert parameter_correlation(trace, ["K", "Sy"]).at["K", "Sy"] < 0.0
    matrix = parameter_correlation(trace, ["K", "Sy"], below_cost=2.0)
    assert matrix.dtypes.eq(float).all()
    assert bool(matrix.isna().all(axis=None)) is (not expected)


def test_a_constant_column_forms_no_pair() -> None:
    trace = [{"K": x, "Sy": 0.2, "n": 3.0 * x, "cost": 1.0} for x in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)]

    pairs = correlated_parameter_pairs(trace, ["K", "Sy", "n"], threshold=0.0)

    assert [(first, second) for first, second, _ in pairs] == [("K", "n")]


def test_the_worst_pair_comes_first() -> None:
    """A reader with three parameters reads the tightest trade-off first."""
    trace = [
        {"K": k, "Sy": s, "n": n, "objective_total": 1.0}
        for k, s, n in [
            (1.0, 10.0, 1.0),
            (2.0, 9.0, 3.0),
            (3.0, 8.0, 2.0),
            (4.0, 7.0, 5.0),
            (5.0, 6.0, 4.0),
            (6.0, 5.0, 6.0),
        ]
    ]

    pairs = correlated_parameter_pairs(trace, threshold=0.5)

    assert abs(pairs[0][2]) >= abs(pairs[-1][2])


# From test_diagnostics.py
# Unit tests for :mod:`hydromodpy.calibration.optim.diagnostics`.


# ---------------------------------------------------------------------------
# iterations_to_dataframe
# ---------------------------------------------------------------------------
def test_iterations_to_dataframe_flattens_nested_parameters() -> None:
    rows = [
        {"trial": 0, "parameters": {"K": 1.0, "Sy": 0.1}, "cost": 0.5},
        {"trial": 1, "parameters": {"K": 2.0, "Sy": 0.2}, "cost": 0.3},
    ]
    df = iterations_to_dataframe(rows)
    assert "K" in df.columns and "Sy" in df.columns
    assert df["K"].tolist() == [1.0, 2.0]
    assert df["Sy"].tolist() == [0.1, 0.2]
    assert df["cost"].tolist() == [0.5, 0.3]


def test_iterations_to_dataframe_passes_dataframe_through() -> None:
    src = pd.DataFrame({"trial": [0, 1], "K": [1.0, 2.0], "cost": [0.5, 0.3]})
    df = iterations_to_dataframe(src)
    assert df is not src  # copied
    assert list(df.columns) == ["trial", "K", "cost"]


def test_iterations_to_dataframe_empty() -> None:
    assert iterations_to_dataframe([]).empty


# ---------------------------------------------------------------------------
# convergence_rate
# ---------------------------------------------------------------------------
def test_convergence_rate_monotone_decrease_is_positive_slope() -> None:
    # Objective strictly decreasing: best[0]-best[i] = i, so slope == 1.
    rows = [{"trial": i, "cost": 10.0 - i, "parameters": {}} for i in range(10)]
    out = convergence_rate(rows)
    assert out["n_points"] == 10.0
    assert out["slope"] == pytest.approx(1.0, abs=1e-9)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-9)


def test_convergence_rate_flat_trace_has_zero_slope() -> None:
    rows = [{"trial": i, "cost": 3.0, "parameters": {}} for i in range(8)]
    out = convergence_rate(rows)
    assert out["slope"] == pytest.approx(0.0, abs=1e-12)
    # ss_tot == 0 → NaN R^2 by construction.
    assert np.isnan(out["r_squared"])


def test_convergence_rate_handles_nan_values() -> None:
    rows = [
        {"trial": 0, "cost": float("nan"), "parameters": {}},
        {"trial": 1, "cost": 1.0, "parameters": {}},
        {"trial": 2, "cost": 0.5, "parameters": {}},
    ]
    out = convergence_rate(rows)
    assert out["n_points"] == 2.0
    assert np.isfinite(out["slope"])


def test_convergence_rate_too_short() -> None:
    out = convergence_rate([{"trial": 0, "cost": 1.0, "parameters": {}}])
    for key in ("slope", "intercept", "r_squared"):
        assert np.isnan(out[key])
    assert out["n_points"] == 1.0


def test_convergence_rate_accepts_dataframe_and_custom_column() -> None:
    df = pd.DataFrame({"trial": np.arange(5), "score": [5.0, 4.0, 3.0, 2.0, 1.0]})
    out = convergence_rate(df, objective="score")
    assert out["slope"] == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# parameter_correlation
# ---------------------------------------------------------------------------
def test_parameter_correlation_orthogonal_signals_near_zero() -> None:
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


def test_parameter_correlation_perfectly_correlated_gives_one() -> None:
    rows = [{"trial": i, "parameters": {"K": float(i), "Sy": 2.0 * i + 1.0}} for i in range(50)]
    corr = parameter_correlation(rows)
    assert corr.loc["K", "Sy"] == pytest.approx(1.0, abs=1e-9)


def test_parameter_correlation_explicit_parameters_subset() -> None:
    rng = np.random.default_rng(0)
    rows = [
        {
            "trial": i,
            "parameters": {
                "K": float(rng.random()),
                "Sy": float(rng.random()),
                "r": float(rng.random()),
            },
        }
        for i in range(30)
    ]
    corr = parameter_correlation(rows, parameters=["K", "Sy"])
    assert list(corr.columns) == ["K", "Sy"]
    assert "r" not in corr.columns


def test_parameter_correlation_empty() -> None:
    assert parameter_correlation([]).empty


def test_parameter_correlation_single_row_is_all_nan() -> None:
    rows = [{"trial": 0, "parameters": {"K": 1.0, "Sy": 0.2}}]
    corr = parameter_correlation(rows)
    assert corr.shape == (2, 2)
    assert corr.isna().all().all()


# From test_the_report_qualifies_its_value.py
# A reported value has to carry how well the search determined it.
#
# Two defects, one place. The trace handed to the diagnostics named its cost
# column ``objective_total``, which is not one of the meta names, so the cost was
# read as if it were another calibrated parameter: a search on one parameter could
# report "K and objective_total moved together", which is not a statement about
# identifiability at all.
#
# And nothing measured the width of the optimum. The report gave a number, and a
# number is the same whether the cost climbs steeply on both sides of it or is
# flat over three decades.


def _trace__report_qualifies() -> list[dict[str, object]]:
    return [
        {"iter": 0, "parameters": {"K": 1.0}, "cost": 9.0},
        {"iter": 1, "parameters": {"K": 2.0}, "cost": 4.0},
        {"iter": 2, "parameters": {"K": 3.0}, "cost": 1.0},
        {"iter": 3, "parameters": {"K": 4.0}, "cost": 1.02},
    ]


def test_the_cost_is_never_read_as_a_parameter() -> None:
    """A single-parameter search cannot have a correlated pair."""
    assert correlated_parameter_pairs(_trace__report_qualifies()) == []


def test_naming_the_parameters_keeps_the_answer_the_same() -> None:
    assert correlated_parameter_pairs(_trace__report_qualifies(), ["K"]) == []


def test_two_parameters_moving_together_are_still_reported() -> None:
    trace = [
        {"iter": i, "parameters": {"K": float(i), "Sy": float(i) * 2.0}, "cost": 1.0}
        for i in range(6)
    ]

    (pair,) = correlated_parameter_pairs(trace)

    assert {pair[0], pair[1]} == {"K", "Sy"}


def test_the_interval_qualifies_the_reported_value() -> None:
    (interval,) = margin_intervals(_trace__report_qualifies(), bounds={"K": (1.0, 4.0)})

    assert interval.best == 3.0
    assert interval.lower == 3.0
    assert interval.upper == 4.0
    assert interval.reaches_upper_bound is True
    assert (interval.to_dict()["lower_end"], interval.to_dict()["upper_end"]) == ("open", "bound")


class _Item:
    def __init__(self, trial_id: int, cost: float) -> None:
        self.trial_id = trial_id
        self.cost = cost


def test_the_runner_builds_the_trace_under_the_name_the_diagnostics_read() -> None:
    history = [_Item(0, 9.0), _Item(1, 1.0), _Item(2, 1.01)]
    values = {0: {"K": 1.0}, 1: {"K": 2.0}, 2: {"K": 3.0}}

    trace = calibration_trace(history, values)

    assert [row["cost"] for row in trace] == [9.0, 1.0, 1.01]
    assert correlated_parameter_pairs(trace, ["K"]) == []


def test_a_trial_with_no_recorded_values_is_left_out() -> None:
    trace = calibration_trace([_Item(0, 1.0), _Item(7, 2.0)], {0: {"K": 1.0}})

    assert len(trace) == 1


# ---------------------------------------------------------------------------
# optim_progress_reporter
# Tests of `optim.progress_reporter`.
# ---------------------------------------------------------------------------

# From test_the_progress_line_names_what_the_method_answers.py
# The live progress line names what the method will answer with.
#
# A root search answers with a root. Its lowest cost is often a trial far from
# it: on the Nancon two-bound search, the bar read ``best 71.8`` at K = 1e-7
# while the session answered K = 5.9e-6. The line of a root search names its
# bracket, then the root, never a minimum cost.


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
    """Record every description the reporter draws, without a console."""
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
    """A cost lowest far from the combined root, as on the Nancon."""
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


def _one_bound(sugg: ParamSuggestion) -> EvaluationResult:
    residual = staircase(ROOT_MAX, float(sugg.values["K"]), 200.0)
    return result_of(sugg, abs(residual), components={"net.J_signed": residual})


def _search(adapter: BisectionAdapter, evaluator, reporter):
    return run_engine(adapter.space, adapter, evaluator, AUTO_BUDGET, progress=reporter)


def test_a_two_root_search_ends_on_the_root_it_returns(handles) -> None:
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


def test_a_one_root_search_shows_the_bracket_around_the_root(handles) -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01)
    reporter = ConsoleProgressReporter(
        "bisection", adapter.counted_budget.worst, label=adapter.progress_label
    )

    _search(adapter, _one_bound, reporter)

    last = handles[0].descriptions[-1]
    assert last.startswith("Calibrating (bisection) - root K in [")
    low, high = (float(end) for end in last.split("[")[1].rstrip("]").split(", "))
    assert low <= ROOT_MAX * 1.001 and high >= ROOT_MAX * 0.999


def test_a_method_without_a_label_keeps_the_lowest_cost(handles) -> None:
    reporter = ConsoleProgressReporter("grid", 2)
    reporter.update(1, EvaluationResult(trial_id=1, sim_id=None, cost=0.5, status="completed"))
    reporter.update(2, EvaluationResult(trial_id=2, sim_id=None, cost=0.25, status="completed"))
    reporter.close()

    assert handles[0].descriptions[-1] == "Calibrating (grid) - best 0.25"


def test_crashed_and_cached_trials_are_counted_in_the_line(handles) -> None:
    reporter = ConsoleProgressReporter("grid", 2)
    reporter.update(1, EvaluationResult(trial_id=1, sim_id=None, cost=1.0, status="failed"))
    reporter.update(
        2, EvaluationResult(trial_id=2, sim_id=None, cost=0.5, status="completed", from_cache=True)
    )

    assert handles[0].descriptions[-1] == "Calibrating (grid) - best 0.5, 1 crashed, 1 cached"


def test_a_closed_reporter_does_not_redraw(handles) -> None:
    reporter = ConsoleProgressReporter("grid", 2)
    reporter.update(1, EvaluationResult(trial_id=1, sim_id=None, cost=0.5, status="completed"))
    reporter.refresh()
    reporter.close()
    reporter.close()
    drawn = list(handles[0].descriptions)
    reporter.refresh()

    assert handles[0].descriptions == drawn
    assert drawn[-1] == "Calibrating (grid) - best 0.5"
