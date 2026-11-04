"""Tests of `optim.diagnostics`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.optim.cost_margin import margin_intervals
from hydromodpy.calibration.optim.diagnostics import (
    convergence_rate,
    correlated_parameter_pairs,
    iterations_to_dataframe,
    parameter_correlation,
)
from hydromodpy.calibration.runners.cli_runner import calibration_trace

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
    trace = _trace([(1.0, 10.0), (2.0, 9.0), (3.0, 8.0), (4.0, 7.0), (5.0, 6.0)])

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
        for i in range(5)
    ]

    (pair,) = correlated_parameter_pairs(trace)

    assert {pair[0], pair[1]} == {"K", "Sy"}


def test_the_interval_qualifies_the_reported_value() -> None:
    (interval,) = margin_intervals(_trace__report_qualifies(), bounds={"K": (1.0, 4.0)})

    assert interval.best == 3.0
    assert interval.lower == 3.0
    assert interval.upper == 4.0
    assert interval.reaches_upper_bound is True


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
