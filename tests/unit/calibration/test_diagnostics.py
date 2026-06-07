"""Unit tests for :mod:`hydromodpy.calibration.diagnostics`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.diagnostics import (
    convergence_rate,
    iterations_to_dataframe,
    parameter_correlation,
)

# ---------------------------------------------------------------------------
# iterations_to_dataframe
# ---------------------------------------------------------------------------


def test_iterations_to_dataframe_flattens_nested_parameters() -> None:
    rows = [
        {"iteration": 0, "parameters": {"K": 1.0, "Sy": 0.1}, "objective_value": 0.5},
        {"iteration": 1, "parameters": {"K": 2.0, "Sy": 0.2}, "objective_value": 0.3},
    ]
    df = iterations_to_dataframe(rows)
    assert "K" in df.columns and "Sy" in df.columns
    assert df["K"].tolist() == [1.0, 2.0]
    assert df["Sy"].tolist() == [0.1, 0.2]
    assert df["objective_value"].tolist() == [0.5, 0.3]


def test_iterations_to_dataframe_passes_dataframe_through() -> None:
    src = pd.DataFrame({"iteration": [0, 1], "K": [1.0, 2.0], "objective_value": [0.5, 0.3]})
    df = iterations_to_dataframe(src)
    assert df is not src  # copied
    assert list(df.columns) == ["iteration", "K", "objective_value"]


def test_iterations_to_dataframe_empty() -> None:
    assert iterations_to_dataframe([]).empty


# ---------------------------------------------------------------------------
# convergence_rate
# ---------------------------------------------------------------------------


def test_convergence_rate_monotone_decrease_is_positive_slope() -> None:
    # Objective strictly decreasing: best[0]-best[i] = i, so slope == 1.
    rows = [{"iteration": i, "objective_value": 10.0 - i, "parameters": {}} for i in range(10)]
    out = convergence_rate(rows)
    assert out["n_points"] == 10.0
    assert out["slope"] == pytest.approx(1.0, abs=1e-9)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-9)


def test_convergence_rate_flat_trace_has_zero_slope() -> None:
    rows = [{"iteration": i, "objective_value": 3.0, "parameters": {}} for i in range(8)]
    out = convergence_rate(rows)
    assert out["slope"] == pytest.approx(0.0, abs=1e-12)
    # ss_tot == 0 → NaN R^2 by construction.
    assert np.isnan(out["r_squared"])


def test_convergence_rate_handles_nan_values() -> None:
    rows = [
        {"iteration": 0, "objective_value": float("nan"), "parameters": {}},
        {"iteration": 1, "objective_value": 1.0, "parameters": {}},
        {"iteration": 2, "objective_value": 0.5, "parameters": {}},
    ]
    out = convergence_rate(rows)
    assert out["n_points"] == 2.0
    assert np.isfinite(out["slope"])


def test_convergence_rate_too_short() -> None:
    out = convergence_rate([{"iteration": 0, "objective_value": 1.0, "parameters": {}}])
    for key in ("slope", "intercept", "r_squared"):
        assert np.isnan(out[key])
    assert out["n_points"] == 1.0


def test_convergence_rate_accepts_dataframe_and_custom_column() -> None:
    df = pd.DataFrame({"iteration": np.arange(5), "objective": [5.0, 4.0, 3.0, 2.0, 1.0]})
    out = convergence_rate(df, objective="objective")
    assert out["slope"] == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# parameter_correlation
# ---------------------------------------------------------------------------


def test_parameter_correlation_orthogonal_signals_near_zero() -> None:
    rng = np.random.default_rng(42)
    n = 400
    a = rng.standard_normal(n)
    b = rng.standard_normal(n)  # independent
    rows = [{"iteration": i, "parameters": {"K": float(a[i]), "Sy": float(b[i])}} for i in range(n)]
    corr = parameter_correlation(rows)
    assert list(corr.columns) == ["K", "Sy"]
    assert corr.loc["K", "K"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["Sy", "Sy"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["K", "Sy"] == pytest.approx(corr.loc["Sy", "K"])
    assert abs(corr.loc["K", "Sy"]) < 0.2


def test_parameter_correlation_perfectly_correlated_gives_one() -> None:
    rows = [{"iteration": i, "parameters": {"K": float(i), "Sy": 2.0 * i + 1.0}} for i in range(50)]
    corr = parameter_correlation(rows)
    assert corr.loc["K", "Sy"] == pytest.approx(1.0, abs=1e-9)


def test_parameter_correlation_explicit_parameters_subset() -> None:
    rng = np.random.default_rng(0)
    rows = [
        {
            "iteration": i,
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
    rows = [{"iteration": 0, "parameters": {"K": 1.0, "Sy": 0.2}}]
    corr = parameter_correlation(rows)
    assert corr.shape == (2, 2)
    assert corr.isna().all().all()
