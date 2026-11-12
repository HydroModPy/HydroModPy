"""Properties of the monotone bed fit (m) on trees of pixels 25 m apart.

The fit pools rising edges to their mean, then tilts blocks so every edge drops
at least min_slope (m/m). These tests check it against a least-squares
reference, a mean bias bound and the closing pass, on chains and random trees.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import lsq_linear

from hydromodpy.catchment.algorithms.bed_regularization import FLAT_TOL_M, regularize_bed_on_tree

LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4  # m/m


def chain_receiver(n_nodes):
    return np.r_[np.arange(1, n_nodes), -1]


def exact_fit(values, receiver, cut):
    # Bounded least squares: a node is its receiver plus a non-negative step,
    # a root (or the node above a cut) is free.
    n = values.size
    down = np.where(cut, -1, receiver)
    # x = path @ t: a node is the sum of the steps from its root down to it.
    path = np.zeros((n, n))
    for node in range(n):
        current = node
        while current >= 0:
            path[node, current] = 1.0
            current = int(down[current])
    lower = np.where(down >= 0, 0.0, -np.inf)
    result = lsq_linear(path, values, bounds=(lower, np.inf), method="bvls", tol=1e-14)
    return path @ result.x


def test_exact_least_squares_on_small_trees():
    # With min_slope = 0 the fit must be the reference, so a pooling without
    # the frontier re-exposure (or none at all) fails here.
    rng = np.random.default_rng(1999)
    worst = 0.0
    for _ in range(300):
        n = int(rng.integers(3, 14))
        # Receivers point to a lower index, so a node's root is node 0 or a cut.
        receiver = np.r_[-1, [rng.integers(0, i) for i in range(1, n)]].astype(np.int64)
        values = rng.normal(0.0, 1.0, n)
        cut = (rng.random(n) < 0.1) & (receiver >= 0)

        fit = regularize_bed_on_tree(values, receiver, np.full(n, LENGTH_M), cut=cut, min_slope=0.0)

        worst = max(worst, float(np.abs(fit.values - exact_fit(values, receiver, cut)).max()))
        assert fit.rises_after_fit == 0
        assert fit.closing_raised == 0
    assert worst < 1e-8


def test_two_rises_pool_again_once_they_cross():
    # Chain, head first: 3, 1, 2, 0, 4. The rise 1 -> 2 pools to 1.5 first, the
    # rise 0 -> 4 pools to 2 later and sits above it. The four lower nodes end
    # in one block at 1.75, the least-squares solution.
    values = np.array([3.0, 1.0, 2.0, 0.0, 4.0])

    fit = regularize_bed_on_tree(values, chain_receiver(5), np.ones(5), min_slope=0.0)

    np.testing.assert_allclose(fit.values, [3.0, 1.75, 1.75, 1.75, 1.75], atol=1e-12)
    assert (fit.violations_before, fit.violations_after) == (2, 0)
    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [1, 2, 3, 4])


def test_mean_of_a_symmetric_noise_is_kept():
    # Pooling conserves the sum of the bed. Without a minimum drop only the
    # flat-run pass moves values, by less than FLAT_TOL_M. The minimum drop
    # only raises, by at most min_slope times the longest pooled run (a few
    # millimeters here, against a 0.3 m noise).
    n_nodes = 1000
    rng = np.random.default_rng(7)
    bed = 1.0e-3 * LENGTH_M * np.arange(n_nodes - 1, -1, -1)
    values = bed + rng.uniform(-0.3, 0.3, n_nodes)
    receiver = chain_receiver(n_nodes)
    length = np.full(n_nodes, LENGTH_M)

    flat = regularize_bed_on_tree(values, receiver, length, min_slope=0.0)
    fit = regularize_bed_on_tree(values, receiver, length, min_slope=MIN_SLOPE)

    assert fit.raised > 100 and fit.lowered > 100
    assert abs(flat.mean_bias_m) < FLAT_TOL_M
    longest_run_m = LENGTH_M * max(block.nodes.size for block in fit.blocks)
    assert 0.0 <= fit.mean_bias_m <= MIN_SLOPE * longest_run_m


def test_entry_of_a_long_flat_run_keeps_the_minimum_drop():
    # The minimum drop tilts a flat run of 10 pixels about its level and lifts
    # its head by half the tilt. The node just above (10.0002) would end below
    # that head, so the closing pass raises it by just enough.
    run = 10
    values = np.r_[11.0, 10.0002, np.full(run, 10.0), 9.0]

    fit = regularize_bed_on_tree(
        values, chain_receiver(values.size), np.full(values.size, LENGTH_M), min_slope=MIN_SLOPE
    )

    lift = MIN_SLOPE * LENGTH_M * (run - 1) / 2
    np.testing.assert_allclose(fit.values[2], 10.0 + lift)
    np.testing.assert_allclose(fit.values[run + 1], 10.0 - lift)
    np.testing.assert_allclose(fit.values[1], 10.0 + lift + MIN_SLOPE * LENGTH_M)
    np.testing.assert_allclose(fit.min_drop_max_lift_m, lift)
    assert fit.rises_after_fit == 0
    assert fit.violations_after == 1
    assert fit.closing_raised == 1
    np.testing.assert_allclose(
        fit.closing_max_raise_m, 10.0 + lift + MIN_SLOPE * LENGTH_M - 10.0002
    )
