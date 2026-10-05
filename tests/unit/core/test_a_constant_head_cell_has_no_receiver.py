"""A constant-head cell has receiver -1: water reaching it leaves the model there.

The cell sits on a slope, so the steepest descent would hand it a lower
neighbour. D sends its upslope cells into it and stops there.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._descent_meshes import grid_descent

N = 7
HEAD = 3 * N + 3


def _slope() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 10.0 + rows + 0.1 * cols


def test_the_constant_head_cell_has_no_receiver() -> None:
    base_level = np.zeros(N * N, dtype=bool)
    base_level[HEAD] = True

    descent = grid_descent(_slope(), base_level=base_level)

    assert int(descent.receiver[HEAD]) == -1
    assert np.isnan(descent.metric.edge_length[HEAD])
    assert int(descent.receiver[HEAD + N]) == HEAD


def test_without_the_constant_head_the_cell_drains_downslope() -> None:
    descent = grid_descent(_slope())

    assert int(descent.receiver[HEAD]) >= 0
