"""A tributary end pooled with the junction alone is a block at a confluence.

Main stem 13, 12, junction 11, root 8; tributary 14, 10 into the junction.
The tributary end stands below the junction and the main stem above it stays
higher: the fit pools the tributary end with the junction only. The junction
has one giver in that block and two in the tree, which is what makes it a
confluence block: the commonest one, raising the tributary and lowering the
main stem.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

LENGTH_M = 25.0

# Main stem: 0 -> 1 -> 2 (junction) -> 3 (root). Tributary: 4 -> 5 -> 2.
JUNCTION, TRIB_END = 2, 5


def test_a_tributary_end_pooled_with_the_junction_is_a_confluence_block() -> None:
    values = np.array([13.0, 12.0, 11.0, 8.0, 14.0, 10.0])
    receiver = np.array([1, 2, 3, -1, 5, 2])

    fit = regularize_bed_on_tree(values, receiver, np.full(6, LENGTH_M))

    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [JUNCTION, TRIB_END])
    assert block.holds_confluence
    np.testing.assert_allclose([block.max_raise_m, block.max_lowering_m], [0.5, 0.5], atol=2e-3)
