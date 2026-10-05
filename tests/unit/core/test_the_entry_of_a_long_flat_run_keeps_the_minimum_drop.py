"""The node just above a long flat run keeps the minimum drop to it.

The minimum drop tilts a flat run about its level, which lifts its head by
``min_slope`` times half its length. A node sitting barely above the run's
raw level would end below the lifted head; the closing pass raises it just
enough, and the fit reports the short edge and the raise.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

RUN = 10
LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4


def test_the_entry_of_a_long_flat_run_keeps_the_minimum_drop() -> None:
    values = np.r_[11.0, 10.0002, np.full(RUN, 10.0), 9.0]
    receiver = np.r_[np.arange(1, values.size), -1]

    fit = regularize_bed_on_tree(
        values, receiver, np.full(values.size, LENGTH_M), min_slope=MIN_SLOPE
    )

    lift = MIN_SLOPE * LENGTH_M * (RUN - 1) / 2
    np.testing.assert_allclose(fit.values[2], 10.0 + lift)
    np.testing.assert_allclose(fit.values[RUN + 1], 10.0 - lift)
    np.testing.assert_allclose(fit.values[1], 10.0 + lift + MIN_SLOPE * LENGTH_M)
    np.testing.assert_allclose(fit.min_drop_max_lift_m, lift)
    assert fit.rises_after_fit == 0
    assert fit.violations_after == 1
    assert fit.closing_raised == 1
    np.testing.assert_allclose(
        fit.closing_max_raise_m, 10.0 + lift + MIN_SLOPE * LENGTH_M - 10.0002
    )
