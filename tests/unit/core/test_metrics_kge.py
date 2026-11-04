"""Unit tests for the KGE metric and miscellaneous error metrics."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.core.metrics import bias, correlation, kge, kge_delta, pbias, rmse


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


def test_pbias_positive_when_sim_overshoots():
    """Σ(sim - obs) is positive when sim > obs, so PBIAS > 0, like bias."""
    obs = np.array([1.0, 2.0, 3.0])
    sim = obs + 1.0
    assert pbias(sim, obs) > 0.0


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


@pytest.mark.parametrize(
    ("sim", "obs", "expected"),
    [
        # Two samples is enough. std(sim)=1, std(obs)=0.5, sums 4 and 3 (population std).
        ([1.0, 3.0], [1.0, 2.0], (1.0, 2.0, 4.0 / 3.0)),
        # cov 0.75, var(sim) 1.5, var(obs) 1.25, sums 12 and 10.
        ([2.0, 2.0, 3.0, 5.0], [1.0, 2.0, 4.0, 3.0], (0.75 / 1.875**0.5, (1.5 / 1.25) ** 0.5, 1.2)),
    ],
)
def test_kge_components_by_hand(sim, obs, expected) -> None:
    r, alpha, beta = expected
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = kge(np.array(sim), np.array(obs))
    score = 1.0 - ((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2) ** 0.5
    assert list(out) == ["kge", "r", "alpha", "beta"]
    assert list(out.values()) == pytest.approx([score, r, alpha, beta])


# Increments of obs at step 1 are 1,2,3,4,5 and of sim 2,1,4,3,6; at step 2 both are 3,5,7,9.
# With a gap in time the runs [0,1,2] and [3,4,5] are differenced apart: obs 1,2,4,5, sim 2,1,3,6.
_OBS = np.array([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])
_SIM = np.array([0.0, 2.0, 3.0, 7.0, 10.0, 16.0])
_GAP = [0, 1, 2, 100, 101, 102]


@pytest.mark.parametrize(
    ("options", "d_sim", "d_obs"),
    [
        ({}, [2, 1, 4, 3, 6], [1, 2, 3, 4, 5]),
        ({"step": 2}, [3, 5, 7, 9], [3, 5, 7, 9]),
        ({"times": _GAP}, [2, 1, 3, 6], [1, 2, 4, 5]),
        ({"step": 2, "times": _GAP}, [3, 9], [3, 9]),
    ],
)
def test_kge_delta_scores_the_increments(options, d_sim, d_obs) -> None:
    assert kge_delta(_SIM, _OBS, **options) == pytest.approx(kge(np.array(d_sim), np.array(d_obs)))


def test_kge_delta_without_increments_is_a_silent_nan() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = kge_delta(_SIM[:2], _OBS[:2])
    assert list(out) == ["kge", "r", "alpha", "beta"]
    assert all(np.isnan(v) for v in out.values())


def test_kge_nan_keeps_its_four_keys() -> None:
    with pytest.warns(UserWarning):
        out = kge(np.array([1.0]), np.array([1.0]))
    assert list(out) == ["kge", "r", "alpha", "beta"]
    assert all(np.isnan(v) for v in out.values())
