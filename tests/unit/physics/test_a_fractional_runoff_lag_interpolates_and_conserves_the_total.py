"""A fractional ``runoff_lag`` interpolates between whole-day shifts.

``L = n + f`` reads ``(1 - f) * shift(n) + f * shift(n + 1)``. Away from the
run's edges the delayed series carries the same total as the one it delays;
only what a lag pushes past the last day is missing from it.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import apply_runoff_lag


def test_a_half_day_lag_splits_a_single_pulse_over_its_two_neighbouring_days() -> None:
    series = np.zeros((10, 1))
    series[3, 0] = 8.0

    lagged = apply_runoff_lag(series, 2.5)

    assert lagged[5, 0] == pytest.approx(4.0)
    assert lagged[6, 0] == pytest.approx(4.0)
    assert np.all(np.delete(lagged[:, 0], [5, 6]) == 0.0)


def test_a_fractional_lag_conserves_the_total_when_nothing_reaches_the_run_end() -> None:
    rng = np.random.default_rng(5)
    series = rng.uniform(0.0, 10.0, size=(40, 3))
    series[-5:] = 0.0  # keep the last days quiet so nothing is pushed past the end

    lagged = apply_runoff_lag(series, 1.75)

    assert lagged.sum(axis=0) == pytest.approx(series.sum(axis=0))


def test_a_fractional_lag_loses_exactly_the_share_pushed_past_the_run_end() -> None:
    n_days = 10
    series = np.zeros((n_days, 1))
    series[7, 0] = 12.0  # shifted by 2 it still lands on the last day; by 3 it does not
    lag_days = 2.5

    lagged = apply_runoff_lag(series, lag_days)

    # Only the "shift by 2" half of the interpolation survives inside the run
    # (day 9); the "shift by 3" half would land on day 10, past the last day.
    assert lagged[-1, 0] == pytest.approx(6.0)
    assert lagged.sum() == pytest.approx(6.0)
    assert series.sum() - lagged.sum() == pytest.approx(6.0)
