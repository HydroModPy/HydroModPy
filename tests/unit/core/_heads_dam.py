"""A V valley holding a reservoir whose lowest rim is a saddle, not the dam.

``z(row, col) = 1000 - row + 2 |col - AXIS|`` on 10 m cells, as in
``_heads_valley``. A basin of 4 x 3 cells is dug at rows 8 to 11 around the axis
and a dam wall closes it to the south at row 12. The lowest cell of its rim is
east of the wall, at row 12, column 8: the water of the criterion leaves the
basin through that saddle, runs down the east hillside and joins the axis at row
14, so the cell at the foot of the dam (row 13, on the axis) lies on no descent
of the mapped heads.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.stream_geometry import NetworkGeometry, build_network_geometry
from hydromodpy.core.stream_heads import HeadCandidates, HeadsSettings
from tests._helpers.ugrid_meshes import quad_mesh

N_ROWS = 24
N_COLS = 13
AXIS = 6
CELL = 10.0
DAM_FOOT_ROW = 13


def cell(row: int, col: int) -> int:
    """Return the index of one cell."""
    return row * N_COLS + col


def centre(row: int, col: int) -> tuple[float, float]:
    """Return the centre of one cell."""
    return ((col + 0.5) * CELL, (row + 0.5) * CELL)


def topography() -> np.ndarray:
    """Return the valley with its basin and its dam wall."""
    rows, cols = np.divmod(np.arange(N_ROWS * N_COLS), N_COLS)
    z = (1000.0 - rows + 2.0 * np.abs(cols - AXIS)).reshape(N_ROWS, N_COLS)
    z[8:12, 5:8] -= 10.0
    z[12, 4:8] = 1010.0
    return z.ravel()


def upstream_head(forced_cells: list[int] | None = None) -> HeadCandidates:
    """Return the one free end of the map: the axis stream above the basin."""
    head = np.asarray([centre(2, AXIS)])
    end = np.asarray([centre(20, AXIS)])
    return HeadCandidates(
        head_xy=head,
        reach_end_xy=end,
        map_points_xy=np.concatenate([head, end]),
        forced_cells=np.asarray(forced_cells or [], dtype=np.int64),
    )


def dam_geometry(forced_cells: list[int] | None = None) -> NetworkGeometry:
    """Build the criterion geometry of the dammed valley, its map drawn from its head."""
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
    return build_network_geometry(
        topography=topography(),
        face_node_connectivity=connectivity,
        vertices=vertices,
        heads=(upstream_head(forced_cells), HeadsSettings(30.0, 0.0)),
        cell_area_m2=np.full(N_ROWS * N_COLS, CELL * CELL),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
    )
