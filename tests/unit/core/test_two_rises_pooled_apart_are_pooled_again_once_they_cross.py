"""Two rises pooled apart are pooled again once the lower one is pulled up.

Chain, head first: 3, 1, 2, 0, 4. The rise 1 -> 2 pools to 1.5 at its own
turn; the rise 0 -> 4 pools to 2 later, which now sits above the first block.
The frontier re-exposure hands the first block back as a candidate, and the
four lower nodes end in one block at 1.75, the least-squares solution. A
pooling without the re-exposure stops at 1.5 then 2: the fitted values differ
and the residual rise is only hidden by the minimum-drop pass.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree


def test_two_rises_pooled_apart_are_pooled_again_once_they_cross() -> None:
    values = np.array([3.0, 1.0, 2.0, 0.0, 4.0])
    receiver = np.array([1, 2, 3, 4, -1])

    fit = regularize_bed_on_tree(values, receiver, np.ones(5), min_slope=0.0)

    np.testing.assert_allclose(fit.values, [3.0, 1.75, 1.75, 1.75, 1.75], atol=1e-12)
    assert fit.violations_before == 2
    assert fit.violations_after == 0
    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [1, 2, 3, 4])
