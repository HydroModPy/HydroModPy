"""An observed series with no spread beyond rounding scores NaN, not a huge cost.

``nse``, ``nse_delta`` and ``nse_seasonal`` refused a zero denominator only. A
constant series of 0.1 has a mean that is not exactly 0.1 in floating point,
so its deviations summed to about 1e-31 and the efficiency came out near
-1e29: a finite cost the search ranked and the session stored. The same held
for the increments of a regular ramp and for the residual of a purely seasonal
series. A spread below ``SPREAD_FLOOR`` of the observed magnitude is now no
spread.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.metrics import SPREAD_FLOOR, log_nse, nse, nse_delta, nse_seasonal

pytestmark = pytest.mark.unit

RNG = np.random.default_rng(0)


@pytest.mark.parametrize("value", [0.1, 0.3, 1.1, 101.7])
def test_a_constant_series_scores_nan(value: float) -> None:
    obs = np.full(1000, value)
    assert float(np.sum((obs - obs.mean()) ** 2)) > 0.0

    assert np.isnan(nse(obs + RNG.normal(0.0, 0.01, obs.size), obs))
    assert np.isnan(log_nse(obs * 1.01, obs))


def test_the_increments_of_a_regular_ramp_score_nan() -> None:
    obs = np.linspace(0.0, 1.0, 1001)
    sim = obs + RNG.normal(0.0, 0.01, obs.size)

    assert np.isnan(nse_delta(sim, obs))


def test_a_purely_seasonal_series_scores_nan_against_its_own_cycle() -> None:
    t = np.arange(3 * 365, dtype=float)
    obs = 10.0 + 2.0 * np.cos(2.0 * np.pi * t / 365.0) + 0.5 * np.sin(4.0 * np.pi * t / 365.0)

    assert np.isnan(nse_seasonal(obs * 1.01, obs))


def test_a_small_real_spread_is_still_scored() -> None:
    # One millimeter on a hundred meters is ten million times the floor.
    t = np.arange(3 * 365, dtype=float)
    obs = 100.0 + 1e-3 * np.sin(2.0 * np.pi * t / 30.0)
    sim = obs + 1e-4 * np.cos(2.0 * np.pi * t / 7.0)
    assert 1e-3 / 100.0 > 1e6 * SPREAD_FLOOR

    assert np.isfinite(nse(sim, obs))
    assert np.isfinite(nse_delta(sim, obs))
    assert np.isfinite(nse_seasonal(sim, obs))
