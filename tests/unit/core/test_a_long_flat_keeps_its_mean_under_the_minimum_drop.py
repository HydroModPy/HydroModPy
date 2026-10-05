"""A 10 km flat keeps its mean: the minimum drop tilts it about its level.

400 pixels at 300 m, 25 m apart, one pixel above at 300.5 m. The minimum drop
of 1e-4 m/m over 10 km is 1 m: given from the exit up, it would lift the head
of the flat by 1 m and the whole flat by 0.5 m on average. Centred on the
flat's mean it lifts the head by half that, lowers the exit as much, and the
flat keeps its level. The largest lift is reported.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

FLAT = 400
LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4


def test_a_long_flat_keeps_its_mean_under_the_minimum_drop() -> None:
    values = np.r_[300.5, np.full(FLAT, 300.0)]
    receiver = np.r_[np.arange(1, values.size), -1]

    fit = regularize_bed_on_tree(
        values, receiver, np.full(values.size, LENGTH_M), min_slope=MIN_SLOPE
    )

    flat = fit.values[1:]
    half_tilt = MIN_SLOPE * LENGTH_M * (FLAT - 1) / 2
    np.testing.assert_allclose(flat.mean(), 300.0, atol=1e-9)
    np.testing.assert_allclose([flat[0], flat[-1]], [300.0 + half_tilt, 300.0 - half_tilt])
    np.testing.assert_allclose(fit.min_drop_max_lift_m, half_tilt)
    assert np.all(-np.diff(fit.values) >= MIN_SLOPE * LENGTH_M - 1e-9)
    assert abs(fit.mean_bias_m) < 0.01
