"""A flat beside the channel drains into the channel, not along it.

A flat valley floor (1 m) is closed by a high rim, with the spill point at the
downstream end of the channel A that runs down its middle. The plain flood
grows the flat from the spill point, so the floor runs beside A down to the
outlet. With A pinned, the floor rises twice as fast away from the channel as
along it and each floor cell joins A within its lateral distance.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.descent import Descent, build_descent
from hydromodpy.core.field_routing import domain_edge_cells
from tests.unit.core._descent_meshes import grid_centres, grid_descent, triangle_mesh

N_ROWS, N_COLS, AXIS = 15, 9, 4
FLOOR, RIM = 1.0, 10.0


def _quad_valley() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    top = np.full((N_ROWS, N_COLS), FLOOR)
    top[0, :] = top[-1, :] = top[:, 0] = top[:, -1] = RIM
    top[0, AXIS] = 0.0
    channel = np.zeros(N_ROWS * N_COLS, dtype=bool)
    pins = np.full(N_ROWS * N_COLS, -1, dtype=int)
    for row in range(N_ROWS - 1):
        channel[row * N_COLS + AXIS] = True
        if row > 0:
            pins[row * N_COLS + AXIS] = (row - 1) * N_COLS + AXIS
    return top, channel, pins


def _triangle_valley() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[np.ndarray, ...]]:
    vertices, connectivity, centroids = triangle_mesh(N_ROWS, N_COLS)
    n_cells = connectivity.shape[0]
    rim = domain_edge_cells(connectivity, np.ones(n_cells, dtype=bool))
    top = np.where(rim, RIM, FLOOR)
    channel = np.zeros(n_cells, dtype=bool)
    pins = np.full(n_cells, -1, dtype=int)
    # Square s holds the triangles 2s (on its lower edge) and 2s + 1 (on its upper edge).
    for row in range(N_ROWS - 1):
        square = row * N_COLS + AXIS
        channel[[2 * square, 2 * square + 1]] = True
        pins[2 * square + 1] = 2 * square
        if row > 0:
            pins[2 * square] = 2 * (square - N_COLS) + 1
    top[2 * AXIS] = 0.0
    return top, channel, pins, (vertices, connectivity, centroids)


def _worst_run_beside(descent: Descent, centres: np.ndarray, channel: np.ndarray) -> float:
    """Largest distance a floor cell runs down-valley beyond its lateral distance to A."""
    floor = descent.routable & ~channel & (descent.surface < 0.5 * (FLOOR + RIM))
    worst = -np.inf
    for start in np.flatnonzero(floor).tolist():
        cell = start
        while not channel[cell] and descent.receiver[cell] >= 0:
            cell = int(descent.receiver[cell])
        assert channel[cell], f"floor cell {start} never reaches the channel"
        lateral = abs(centres[start, 0] - (AXIS + 0.5))
        worst = max(worst, centres[start, 1] - centres[cell, 1] - lateral)
    return worst


def test_on_a_quad_grid() -> None:
    top, channel, pins = _quad_valley()
    centres = grid_centres(N_ROWS, N_COLS)

    descent = grid_descent(top, channel=channel, pinned_receiver=pins)

    assert _worst_run_beside(descent, centres, channel) <= 1.0


def test_on_a_triangle_mesh() -> None:
    top, channel, pins, (vertices, connectivity, centroids) = _triangle_valley()

    descent = build_descent(
        top,
        connectivity,
        vertices=vertices,
        centroids=centroids,
        routable=np.ones(top.size, dtype=bool),
        channel=channel,
        pinned_receiver=pins,
    )

    assert _worst_run_beside(descent, centroids, channel) <= 1.0


@pytest.mark.parametrize("mesh", ["quad", "triangle"])
def test_without_pins_the_floor_runs_beside_the_channel(mesh: str) -> None:
    if mesh == "quad":
        top, channel, _ = _quad_valley()
        centres = grid_centres(N_ROWS, N_COLS)
        descent = grid_descent(top)
    else:
        top, channel, _, (vertices, connectivity, centres) = _triangle_valley()
        descent = build_descent(
            top,
            connectivity,
            vertices=vertices,
            centroids=centres,
            routable=np.ones(top.size, dtype=bool),
        )

    assert _worst_run_beside(descent, centres, channel) > 5.0
