"""A forest of two roots is fitted tree by tree.

Each tree gets exactly the fit it would get alone, and no pooled block
spans both trees.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

LENGTH_M = 25.0


def test_a_forest_is_fitted_tree_by_tree() -> None:
    first = np.array([6.0, 4.0, 5.0, 1.0])
    second = np.array([3.0, 2.5, 2.9, 2.0, 0.5])
    first_receiver = np.array([1, 2, 3, -1])
    second_receiver = np.array([1, 2, 3, 4, -1])
    values = np.r_[first, second]
    receiver = np.r_[
        first_receiver, np.where(second_receiver >= 0, second_receiver + first.size, -1)
    ]

    forest = regularize_bed_on_tree(values, receiver, np.full(values.size, LENGTH_M))
    alone_first = regularize_bed_on_tree(first, first_receiver, np.full(first.size, LENGTH_M))
    alone_second = regularize_bed_on_tree(second, second_receiver, np.full(second.size, LENGTH_M))

    np.testing.assert_array_equal(forest.values, np.r_[alone_first.values, alone_second.values])
    assert len(forest.blocks) == 2
    for block in forest.blocks:
        assert np.all(block.nodes < first.size) or np.all(block.nodes >= first.size)
    assert forest.violations_after == 0
