"""A tributary ending below the junction shares one block with the main stem.

The junction pixel stands above both of its upstream neighbours: the end of
the tributary and the main stem just upstream. The fit pools the three into
one block that raises the tributary end and the main stem above, lowers the
junction, and the block reports that it holds a confluence. The minimum drop
tilts the block about its mean: its two heads lie one edge above the junction,
a third of the way, on average, from it.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4

# Main stem: 0 (head) -> 1 -> 2 (junction) -> 3 (root). Tributary: 4 (head) -> 5 -> 2.
HEAD, MAIN_ABOVE, JUNCTION, ROOT, TRIB_HEAD, TRIB_END = range(6)


def test_a_tributary_ending_below_the_junction_shares_a_block_with_the_main_stem() -> None:
    values = np.array([13.0, 10.4, 11.0, 8.0, 14.0, 10.0])
    receiver = np.array([1, 2, 3, -1, 5, 2])

    fit = regularize_bed_on_tree(values, receiver, np.full(6, LENGTH_M), min_slope=MIN_SLOPE)

    mean = (10.4 + 11.0 + 10.0) / 3.0
    drop = MIN_SLOPE * LENGTH_M
    head, exit_ = mean + drop / 3.0, mean - 2.0 * drop / 3.0
    np.testing.assert_allclose(fit.values[[MAIN_ABOVE, JUNCTION, TRIB_END]], [head, exit_, head])
    np.testing.assert_allclose(fit.values[[HEAD, ROOT, TRIB_HEAD]], [13.0, 8.0, 14.0])
    assert fit.values[TRIB_END] > values[TRIB_END]
    assert fit.values[JUNCTION] < values[JUNCTION]
    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [MAIN_ABOVE, JUNCTION, TRIB_END])
    assert block.holds_confluence
    np.testing.assert_allclose(block.max_raise_m, head - 10.0)
    np.testing.assert_allclose(block.max_lowering_m, 11.0 - exit_)
    assert fit.violations_after == 0
