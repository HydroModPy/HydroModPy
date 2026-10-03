"""An integer ``runoff_lag`` shifts the routed runoff series by whole days.

``apply_runoff_lag`` is the pure delay applied after the ``runoff_time``
reservoir. At an integer lag it is a plain shift: day ``t`` reads what day
``t - n`` held, with zero (no history) or the supplied history before day 0.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import apply_runoff_lag


def test_a_three_day_lag_shifts_a_random_series_without_history() -> None:
    rng = np.random.default_rng(4)
    series = rng.uniform(0.0, 10.0, size=(30, 5))

    lagged = apply_runoff_lag(series, 3.0)

    assert np.array_equal(lagged[3:], series[:-3])
    assert np.all(lagged[:3] == 0.0)


def test_a_one_day_lag_reads_the_supplied_history_before_day_zero() -> None:
    series = np.zeros((5, 1))
    history = np.array([[1.0], [2.0], [3.0]])  # days -3, -2, -1

    lagged = apply_runoff_lag(series, 1.0, history_mm=history)

    # day 0 reads day -1 of the history (3.0); the rest is still zero.
    assert lagged[0, 0] == 3.0
    assert np.all(lagged[1:, 0] == 0.0)


def test_a_lag_longer_than_the_available_history_reads_zero_for_the_missing_days() -> None:
    series = np.zeros((3, 1))
    history = np.array([[5.0]])  # only day -1 is known

    lagged = apply_runoff_lag(series, 2.0, history_mm=history)

    # day 0 reads day -2, unknown: zero. Day 1 reads day -1: 5.0.
    assert lagged[0, 0] == 0.0
    assert lagged[1, 0] == 5.0


def test_a_zero_lag_returns_the_series_unchanged() -> None:
    series = np.array([[1.0, 2.0], [3.0, 4.0]])

    lagged = apply_runoff_lag(series, 0.0)

    assert lagged is series
