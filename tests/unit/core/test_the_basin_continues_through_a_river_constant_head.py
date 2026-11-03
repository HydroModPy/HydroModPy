"""The basin of D follows the receivers, so it crosses a river CHD and stops at a CHD sink.

A constant-head cell on a slope keeps its steepest descent: the basin of the
outlet goes on upstream of it. A constant-head cell at the bottom of a bowl has
no lower neighbor: it is a sink, and the cells draining into it stay outside
the basin. The basin never reads the stopping receiver, which ends every walk
at a constant-head cell.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.descent import descent_basin
from tests._helpers.descent_cases import grid_centres, grid_descent

N = 9
HEAD = 4 * N + 4
OUTLET = 0


def _slope() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 10.0 + rows + 0.1 * cols


def _head_at(cell: int) -> np.ndarray:
    base_level = np.zeros(N * N, dtype=bool)
    base_level[cell] = True
    return base_level


def _basin_at_the_outlet(descent):
    return descent_basin(
        descent, cell_area_m2=np.ones(N * N), near=tuple(grid_centres(N, N)[OUTLET])
    )


def test_the_basin_goes_on_upstream_of_a_river_constant_head() -> None:
    descent = grid_descent(_slope(), base_level=_head_at(HEAD))
    assert int(descent.stopping_receiver[HEAD]) == -1

    basin = _basin_at_the_outlet(descent)

    assert basin.outlet == OUTLET
    assert basin.mask[HEAD]
    assert basin.mask[HEAD + N]  # upstream of the constant head
    assert basin.mask.all()
    assert basin.area_m2 == float(N * N)


def test_a_constant_head_sink_keeps_its_bowl_outside_the_basin() -> None:
    top = _slope()
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    bowl = np.maximum(np.abs(rows - 4), np.abs(cols - 4)) <= 1
    top[bowl] = 30.0 + np.hypot(rows - 4, cols - 4)[bowl]
    top[4, 4] = 2.0
    descent = grid_descent(top, base_level=_head_at(HEAD))
    assert int(descent.receiver[HEAD]) == -1

    basin = _basin_at_the_outlet(descent)

    drains_to_head = np.zeros(N * N, dtype=bool)
    for start in range(N * N):
        cell = start
        while cell >= 0 and cell != HEAD:
            cell = int(descent.receiver[cell])
        drains_to_head[start] = cell == HEAD
    assert drains_to_head.sum() > 1
    np.testing.assert_array_equal(basin.mask, ~drains_to_head)
