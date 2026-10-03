"""A V valley the heads rule is traced on, its streams known in closed form.

``z(row, col) = 1000 - row + 2 |col - AXIS|`` on a grid of 10 m cells: water
runs north along the axis column, and every hillside cell reaches it
diagonally. The outlet is the axis cell of the last row.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.stream_geometry import NetworkGeometry, build_network_geometry
from hydromodpy.core.stream_heads import HeadCandidates, HeadsSettings
from tests._helpers.ugrid_meshes import quad_mesh

N_ROWS = 30
N_COLS = 21
AXIS = 10
CELL = 10.0


def centre(row: int, col: int) -> tuple[float, float]:
    """Return the centre of one cell."""
    return ((col + 0.5) * CELL, (row + 0.5) * CELL)


def cell(row: int, col: int) -> int:
    """Return the index of one cell."""
    return row * N_COLS + col


def candidates(pairs: list[tuple[tuple[float, float], tuple[float, float]]]) -> HeadCandidates:
    """Return candidates from ``(head, reach end)`` pairs, the map sampled at both."""
    heads = np.asarray([head for head, _ in pairs], dtype=float).reshape(-1, 2)
    ends = np.asarray([end for _, end in pairs], dtype=float).reshape(-1, 2)
    return HeadCandidates(
        head_xy=heads, reach_end_xy=ends, map_points_xy=np.concatenate([heads, ends])
    )


def valley_geometry(
    heads: HeadCandidates,
    *,
    snap_radius_m: float = 100.0,
    min_drained_area_m2: float = 0.0,
) -> NetworkGeometry:
    """Build the criterion geometry of the valley, its map drawn from ``heads``."""
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
    rows, cols = np.divmod(np.arange(N_ROWS * N_COLS), N_COLS)
    return build_network_geometry(
        topography=1000.0 - rows + 2.0 * np.abs(cols - AXIS),
        face_node_connectivity=connectivity,
        vertices=vertices,
        heads=(heads, HeadsSettings(snap_radius_m, min_drained_area_m2)),
        cell_area_m2=np.full(N_ROWS * N_COLS, CELL * CELL),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
    )
