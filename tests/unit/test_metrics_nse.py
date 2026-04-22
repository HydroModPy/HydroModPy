"""Unit tests for the NSE metric."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.metrics import log_nse, nse


def test_nse_perfect_match_is_one():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert nse(obs, obs) == pytest.approx(1.0)


def test_nse_climatology_is_zero():
    """Predicting the mean gives NSE = 0 by construction."""
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sim = np.full_like(obs, obs.mean())
    assert nse(sim, obs) == pytest.approx(0.0)


def test_nse_negative_when_worse_than_mean():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sim = obs[::-1]  # totally inverted
    assert nse(sim, obs) < 0.0


def test_nse_drops_nans_in_either_series():
    obs = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    sim = np.array([1.1, np.nan, 3.0, 4.0, 5.0])
    # Pairs left: (4.0, 4.0), (5.0, 5.0). Single point (1.1, 1.0) stays too.
    score = nse(sim, obs)
    assert np.isfinite(score)


def test_nse_constant_obs_returns_nan():
    obs = np.full(5, 3.0)
    sim = np.array([3.1, 2.9, 3.0, 3.0, 3.1])
    assert np.isnan(nse(sim, obs))


def test_nse_shape_mismatch_raises():
    with pytest.raises(ValueError):
        nse(np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0]))


def test_nse_returns_python_float():
    score = nse(np.array([1.0, 2.0]), np.array([1.1, 2.1]))
    assert isinstance(score, float)


def test_log_nse_rejects_negative_values():
    with pytest.raises(ValueError):
        log_nse(np.array([-1.0, 2.0]), np.array([1.0, 2.0]))


def test_log_nse_perfect_match():
    obs = np.array([1.0, 10.0, 100.0])
    assert log_nse(obs, obs) == pytest.approx(1.0)
