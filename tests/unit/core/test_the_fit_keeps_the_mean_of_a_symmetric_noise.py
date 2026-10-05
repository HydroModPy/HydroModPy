"""The fit keeps the mean of a symmetric noise around a straight bed.

The pooling replaces each block by its mean, so it conserves the sum of the
bed exactly. With no minimum drop the only change is the flat-run pass
snapping values closer than ``FLAT_TOL_M`` to their run exit, so the bias
stays far under ``FLAT_TOL_M``. The minimum
drop only raises, by ``min_slope`` times the distance to the exit of a flat
block, so the bias is non-negative and bounded by ``min_slope`` times the
longest pooled run. With 25 m pixels and runs of a few dozen pixels that is a
few millimetres, against a 0.3 m noise: the tolerance is that bound, not a
guess.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import FLAT_TOL_M, regularize_bed_on_tree

N_NODES = 1000
LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4


def test_the_fit_keeps_the_mean_of_a_symmetric_noise() -> None:
    rng = np.random.default_rng(7)
    bed = 1.0e-3 * LENGTH_M * np.arange(N_NODES - 1, -1, -1)
    values = bed + rng.uniform(-0.3, 0.3, N_NODES)
    receiver = np.r_[np.arange(1, N_NODES), -1]
    length = np.full(N_NODES, LENGTH_M)

    flat = regularize_bed_on_tree(values, receiver, length, min_slope=0.0)
    fit = regularize_bed_on_tree(values, receiver, length, min_slope=MIN_SLOPE)

    assert fit.raised > 100 and fit.lowered > 100
    assert abs(flat.mean_bias_m) < FLAT_TOL_M
    longest_run_m = LENGTH_M * max(block.nodes.size for block in fit.blocks)
    assert 0.0 <= fit.mean_bias_m <= MIN_SLOPE * longest_run_m
