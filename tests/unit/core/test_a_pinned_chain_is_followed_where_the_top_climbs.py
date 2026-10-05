"""A pinned channel cell drains to its pin, even where T climbs along the channel.

The channel A runs down column 3 to the outlet at row 0. At row 4 it crosses a
sill of T (4 m) while the valley side at (4, 2) offers a gap at 2.5 m. The
steepest descent leaves the channel through the gap; the pins hold it on A, and
the copy is raised along the channel above the sill so each pin stays lower
than its donor.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._descent_meshes import grid_descent

N_ROWS, N_COLS, AXIS = 12, 7, 3
SILL_ROW, SILL, GAP = 4, 4.0, 2.5


def _cell(row: int, col: int) -> int:
    return row * N_COLS + col


def _valley() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N_ROWS), np.arange(N_COLS), indexing="ij")
    top = 5.0 + 2.0 * np.abs(cols - AXIS)
    top[:, AXIS] = 1.0 + 0.1 * np.arange(N_ROWS)
    top[0, :] = top[-1, :] = 20.0
    top[0, AXIS] = 0.0
    top[SILL_ROW, AXIS] = SILL
    top[SILL_ROW, AXIS - 1] = GAP
    return top


def _channel_and_pins() -> tuple[np.ndarray, np.ndarray]:
    channel = np.zeros(N_ROWS * N_COLS, dtype=bool)
    pins = np.full(N_ROWS * N_COLS, -1, dtype=int)
    for row in range(N_ROWS - 1):
        channel[_cell(row, AXIS)] = True
        if row > 0:
            pins[_cell(row, AXIS)] = _cell(row - 1, AXIS)
    return channel, pins


def test_every_channel_cell_drains_to_its_pin() -> None:
    channel, pins = _channel_and_pins()

    descent = grid_descent(_valley(), channel=channel, pinned_receiver=pins)

    for row in range(1, N_ROWS - 1):
        assert int(descent.receiver[_cell(row, AXIS)]) == _cell(row - 1, AXIS)
    assert descent.n_channel == N_ROWS - 1
    assert descent.n_pinned == N_ROWS - 2


def test_the_copy_is_raised_along_the_channel_above_the_sill() -> None:
    top = _valley()
    channel, pins = _channel_and_pins()

    descent = grid_descent(top, channel=channel, pinned_receiver=pins)

    above = [_cell(row, AXIS) for row in range(SILL_ROW + 1, N_ROWS - 1)]
    assert descent.surface[_cell(SILL_ROW, AXIS)] == SILL
    assert np.all(descent.surface[above] > SILL)
    assert np.all(np.diff(descent.surface[above]) > 0.0)
    assert descent.n_pinned_raised == len(above)
    lowest_above = top[SILL_ROW + 1, AXIS]
    assert descent.max_pinned_raise_m > SILL - lowest_above


def test_without_pins_the_descent_leaves_through_the_gap() -> None:
    descent = grid_descent(_valley())

    above_sill = _cell(SILL_ROW + 1, AXIS)
    assert int(descent.receiver[above_sill]) == _cell(SILL_ROW, AXIS - 1)
