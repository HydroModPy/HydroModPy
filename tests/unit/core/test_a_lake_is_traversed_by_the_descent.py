"""A lake is crossed by D, never a sink of it: the cells below its dam drain downstream.

The valley runs west along row 3. From the east: the upstream river, a lake of
four cells, a dam with a carved corridor (5 m), a pit just below the dam (3 m),
a sill (6 m), and the river down to the outlet. The pit's lowest pass is the
corridor, back into the lake. Seeded as a sink, the lake would capture the pit
over the corridor. Traversed, it fills to its spill level and drains through
the corridor, the pit and the sill to the outlet, and so does the pit.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._descent_meshes import grid_descent

N_ROWS = 7
N_COLS = 14
AXIS = 3
VALLEY = {
    0: 0.0,
    1: 1.0,
    2: 2.0,
    3: 6.0,  # the sill below the pit
    4: 3.0,  # the pit just below the dam
    5: 5.0,  # the carved corridor through the dam
    6: 4.0,  # the lake, cols 6 to 9
    7: 3.0,
    8: 3.5,
    9: 4.5,
    10: 8.0,
    11: 9.0,
    12: 10.0,
    13: 11.0,
}
LAKE_COLS = (6, 7, 8, 9)
SILL, PIT, CORRIDOR = AXIS * N_COLS + 3, AXIS * N_COLS + 4, AXIS * N_COLS + 5


def _valley() -> tuple[np.ndarray, np.ndarray]:
    rows, _ = np.meshgrid(np.arange(N_ROWS), np.arange(N_COLS), indexing="ij")
    top = 10.0 + 3.0 * np.abs(rows - AXIS)
    for col, value in VALLEY.items():
        top[AXIS, col] = value
    lake_of = np.full(N_ROWS * N_COLS, -1, dtype=int)
    lake_of[[AXIS * N_COLS + col for col in LAKE_COLS]] = 0
    return top, lake_of


def _walk(receiver: np.ndarray, start: int) -> list[int]:
    path = [start]
    while receiver[path[-1]] >= 0:
        path.append(int(receiver[path[-1]]))
    return path


def test_the_pit_below_the_dam_drains_downstream() -> None:
    top, lake_of = _valley()

    descent = grid_descent(top, lake_of=lake_of)

    assert int(descent.receiver[PIT]) == SILL
    assert _walk(descent.receiver, PIT)[-1] == AXIS * N_COLS


def test_the_lake_spills_through_the_corridor() -> None:
    top, lake_of = _valley()

    descent = grid_descent(top, lake_of=lake_of)

    lake_cells = np.flatnonzero(lake_of == 0)
    lowest = int(lake_cells[np.argmin(descent.surface[lake_cells])])
    assert int(descent.receiver[lowest]) == CORRIDOR
    assert not np.any(descent.base_level[lake_cells])
    assert np.all(descent.surface[lake_cells] >= top.reshape(-1)[lake_cells])


def test_a_cell_above_the_lake_descends_into_it() -> None:
    top, lake_of = _valley()

    descent = grid_descent(top, lake_of=lake_of)

    above = (AXIS - 2) * N_COLS + 8
    assert any(lake_of[cell] == 0 for cell in _walk(descent.receiver, above))
