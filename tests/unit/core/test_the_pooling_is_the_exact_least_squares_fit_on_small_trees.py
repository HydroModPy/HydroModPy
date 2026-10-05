"""The pooling is the exact least-squares isotonic fit, checked on small random trees.

The reference is a bounded linear least squares, solved exactly by BVLS: each
node is its receiver plus a non-negative step, a root (or the node above a
cut) is free. With ``min_slope = 0`` neither the minimum drop nor the closing
pass moves a correct fit, so the fitted values must be the reference. A
pooling without the frontier re-exposure, or none at all, is not.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import lsq_linear

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

N_TREES = 300


def _exact_fit(values: np.ndarray, receiver: np.ndarray, cut: np.ndarray) -> np.ndarray:
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


def test_the_pooling_is_the_exact_least_squares_fit_on_small_trees() -> None:
    rng = np.random.default_rng(1999)
    worst = 0.0
    for _ in range(N_TREES):
        n = int(rng.integers(3, 14))
        # Receivers point to a lower index, so a node's root is node 0 or a cut.
        receiver = np.r_[-1, [rng.integers(0, i) for i in range(1, n)]].astype(np.int64)
        values = rng.normal(0.0, 1.0, n)
        cut = (rng.random(n) < 0.1) & (receiver >= 0)

        fit = regularize_bed_on_tree(values, receiver, np.full(n, 25.0), cut=cut, min_slope=0.0)

        worst = max(worst, float(np.abs(fit.values - _exact_fit(values, receiver, cut)).max()))
        assert fit.rises_after_fit == 0
        assert fit.closing_raised == 0
    assert worst < 1e-8
