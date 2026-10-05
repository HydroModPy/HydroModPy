"""A single rise on a chain is pooled to the mean of its two ends.

The least-squares monotone fit of two values in the wrong order is their mean.
The minimum drop then tilts the pair about that mean so the edge drains.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4


def test_a_single_rise_on_a_chain_is_pooled_to_its_mean() -> None:
    values = np.array([5.0, 4.0, 3.0, 3.6, 2.0])
    receiver = np.array([1, 2, 3, 4, -1])

    fit = regularize_bed_on_tree(values, receiver, np.full(5, LENGTH_M), min_slope=MIN_SLOPE)

    drop = MIN_SLOPE * LENGTH_M
    np.testing.assert_allclose(
        fit.values, [5.0, 4.0, 3.3 + drop / 2, 3.3 - drop / 2, 2.0], atol=1e-12
    )
    assert fit.violations_before == 1
    assert fit.violations_after == 0
    assert np.all(fit.values[:-1] - fit.values[1:] >= drop - 1e-12)
    assert (fit.raised, fit.lowered) == (1, 1)
    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [2, 3])
    assert not block.holds_confluence
    np.testing.assert_allclose(
        [block.max_raise_m, block.max_lowering_m], [0.3 + drop / 2, 0.3 + drop / 2]
    )
