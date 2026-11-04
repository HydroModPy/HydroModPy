"""Unit tests for the NSE metric."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.core.metrics import log_nse, nse, nse_seasonal


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


def test_log_nse_clips_negative_values_to_zero():
    sim, obs = np.array([-1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.5])
    assert log_nse(sim, obs) == pytest.approx(log_nse(np.array([0.0, 2.0, 3.0]), obs))


def test_log_nse_perfect_match():
    obs = np.array([1.0, 10.0, 100.0])
    assert log_nse(obs, obs) == pytest.approx(1.0)


def _cycle(t: np.ndarray) -> np.ndarray:
    angle = 2.0 * np.pi * t / 365.0
    return 10.0 + 2.0 * np.cos(angle) + 0.5 * np.sin(2.0 * angle) + 0.3 * np.cos(2.0 * angle)


def test_nse_seasonal_by_hand_on_exactly_two_cycles() -> None:
    """The ripple sin(2 pi t / 73) is orthogonal to the harmonics over 730 samples.

    The benchmark is then the cycle alone, the denominator is the energy of the
    ripple (365) and a simulation off by half the ripple scores 1 - 0.25.
    """
    t = np.arange(730.0)
    ripple = np.sin(2.0 * np.pi * t / 73.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        score = nse_seasonal(_cycle(t) + 1.5 * ripple, _cycle(t) + ripple)
    assert score == pytest.approx(0.75)


def test_nse_seasonal_of_nothing_is_a_silent_nan() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert np.isnan(nse_seasonal(np.array([]), np.array([])))


def test_nse_seasonal_reads_the_time_axis() -> None:
    """A cycle sampled with a gap is in the span only on its true dates."""
    t = np.concatenate([np.arange(400.0), np.arange(500.0, 830.0)])
    obs = _cycle(t)
    assert np.isnan(nse_seasonal(obs + 1.0, obs, times=t))
    assert np.isfinite(nse_seasonal(obs + 1.0, obs))
