"""Unit tests for the KGE metric and miscellaneous error metrics."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.metrics import bias, correlation, kge, pbias, rmse


def test_kge_perfect_match_returns_one():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = kge(obs, obs)
    assert out["kge"] == pytest.approx(1.0)
    assert out["r"] == pytest.approx(1.0)
    assert out["alpha"] == pytest.approx(1.0)
    assert out["beta"] == pytest.approx(1.0)


def test_kge_components_when_scaled_by_two():
    """sim = 2 * obs gives r=1, alpha=2, beta=2."""
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = kge(2.0 * obs, obs)
    assert out["r"] == pytest.approx(1.0)
    assert out["alpha"] == pytest.approx(2.0)
    assert out["beta"] == pytest.approx(2.0)
    expected = 1.0 - np.sqrt(0.0 + 1.0 + 1.0)
    assert out["kge"] == pytest.approx(expected)


def test_kge_constant_obs_returns_nan():
    out = kge(np.array([1.0, 2.0, 3.0]), np.array([5.0, 5.0, 5.0]))
    assert np.isnan(out["kge"])


def test_kge_empty_intersection_returns_nan():
    out = kge(np.array([np.nan, np.nan]), np.array([1.0, 2.0]))
    assert np.isnan(out["kge"])


def test_rmse_perfect_is_zero():
    obs = np.array([1.0, 2.0, 3.0])
    assert rmse(obs, obs) == pytest.approx(0.0)


def test_rmse_known_value():
    obs = np.array([1.0, 2.0, 3.0])
    sim = np.array([2.0, 3.0, 4.0])
    assert rmse(sim, obs) == pytest.approx(1.0)


def test_bias_signed():
    obs = np.array([1.0, 2.0, 3.0])
    sim = obs + 0.5
    assert bias(sim, obs) == pytest.approx(0.5)


def test_pbias_zero_when_perfect():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert pbias(obs, obs) == pytest.approx(0.0)


def test_pbias_negative_when_sim_overshoots():
    """Σ(obs - sim) is negative when sim > obs, so PBIAS < 0."""
    obs = np.array([1.0, 2.0, 3.0])
    sim = obs + 1.0
    assert pbias(sim, obs) < 0.0


def test_pbias_zero_total_obs_returns_nan():
    obs = np.array([1.0, -1.0, 2.0, -2.0])  # sums to 0
    sim = obs + 0.1
    assert np.isnan(pbias(sim, obs))


def test_correlation_perfect_one():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert correlation(obs, obs) == pytest.approx(1.0)


def test_correlation_anticorrelated():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert correlation(-obs, obs) == pytest.approx(-1.0)
