"""No constrained edge is left short of the minimum drop on a random tree.

A seeded random tree with a noisy bed, a few gaps and a few cuts. The
isotonic fit leaves no rising edge on its own, before the minimum drop and
the closing pass: a pooling without the frontier re-exposure, or no pooling
at all, leaves some and moves the mean. After the closing pass every edge
that is not a cut drops at least ``min_slope`` times its length.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

N_NODES = 2000
MIN_SLOPE = 1.0e-4
NOISE_SD_M = 0.3


def test_no_edge_is_left_short_on_a_random_tree() -> None:
    rng = np.random.default_rng(20261005)
    receiver = np.r_[-1, [rng.integers(max(0, i - 30), i) for i in range(1, N_NODES)]].astype(
        np.int64
    )
    length = rng.choice([25.0, 25.0 * np.sqrt(2.0)], N_NODES)
    distance_to_root = np.zeros(N_NODES)
    for node in range(1, N_NODES):
        distance_to_root[node] = distance_to_root[receiver[node]] + length[node]
    values = 2.0e-3 * distance_to_root + rng.normal(0.0, NOISE_SD_M, N_NODES)
    gap = rng.random(N_NODES) < 0.02
    values[gap] += 3.0
    cut = rng.random(N_NODES) < 0.01

    fit = regularize_bed_on_tree(values, receiver, length, gap=gap, cut=cut, min_slope=MIN_SLOPE)

    edges = np.flatnonzero((receiver >= 0) & ~cut)
    drop = fit.values[edges] - fit.values[receiver[edges]]
    assert fit.violations_before > 100
    assert fit.rises_after_fit == 0
    assert np.all(drop >= MIN_SLOPE * length[edges] - 1e-9)
    # The least-squares fit keeps the mean of the measured bed (1e-4 m here);
    # without the frontier re-exposure the bias is 0.013 m, without pooling 0.24 m.
    assert abs(fit.mean_bias_m) < 0.01
    assert fit.closing_raised >= fit.violations_after > 0
