"""The report counts a lake flooded to its spill apart from a pit filled outside lakes.

On a plane rising to the north-east, one pit lies 2 m below its lowest
neighbour and a lake of four cells lies 6 m below its own. ``n_raised`` and
``max_raise_m`` see the pit alone, ``n_lake_flooded`` and ``max_lake_flood_m``
the lake alone.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.core._descent_meshes import grid_descent

N = 8
PIT = (2, 5)
LAKE = ((5, 5), (5, 6), (6, 5), (6, 6))


def _plane() -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = 10.0 + rows + cols
    top[PIT] = 13.0  # lowest neighbour (1, 4) at 15
    lake_of = np.full(N * N, -1, dtype=int)
    for cell in LAKE:
        top[cell] = 12.0  # lowest neighbour (4, 4) at 18
        lake_of[cell[0] * N + cell[1]] = 0
    return top, lake_of


def test_the_pit_is_counted_as_raised() -> None:
    top, lake_of = _plane()

    descent = grid_descent(top, lake_of=lake_of)

    assert descent.n_raised == 1
    assert descent.max_raise_m == pytest.approx(2.0, abs=0.01)


def test_the_lake_is_counted_as_flooded() -> None:
    top, lake_of = _plane()

    descent = grid_descent(top, lake_of=lake_of)

    assert descent.n_lake_flooded == len(LAKE)
    assert descent.max_lake_flood_m == pytest.approx(6.0, abs=0.01)
