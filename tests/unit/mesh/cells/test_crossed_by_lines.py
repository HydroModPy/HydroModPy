"""A mapped network drawn on mesh cells as WhiteboxTools VectorLinesToRaster draws it.

Abherve et al. (2023) rasterize the mapped network of the stream criterion with
``VectorLinesToRaster``. Its source marks a cell when the line crosses one of the two
medians of that cell: a thin line, neither Bresenham nor all-touched. The medians of a
grid are the segments joining the centers of edge-sharing cells, which is how
``line_crossing_cell_mask`` states the rule on any mesh. The oracle below is the two
loops of the Rust source. Lengths are in meters.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, Point

from hydromodpy.mesh.cells.crossed_by_lines import line_crossing_cell_mask
from hydromodpy.mesh.planar.geometry import cell_polygons
from tests._helpers.mesh_cases import LAMBERT93_WKT, regular_mesh
from tests._helpers.ugrid_meshes import quad_mesh

CRS = LAMBERT93_WKT


def _quad_grid(*, x0: float = 0.0, y0: float = 0.0, size: float = 100.0, n: int = 3):
    """Return (vertices, connectivity) of an ``n x n`` grid of ``size`` m cells, row 0 north."""
    mesh = regular_mesh(n, n, dx=size, xmin=x0, ymin=y0).mesh
    return mesh.vertices, mesh.flat_connectivity


N = 24

RES = 10.0


def _grid():
    vertices, connectivity = quad_mesh(N, N, cell_size=RES)
    rows, cols = np.divmod(np.arange(N * N), N)
    centres = np.column_stack([(cols + 0.5) * RES, (rows + 0.5) * RES])
    return vertices, connectivity, centres, cell_polygons(vertices, connectivity)


GRID = _grid()


def _crossing(lines, grid=GRID, **kwargs):
    vertices, connectivity, centres, polygons = grid
    return line_crossing_cell_mask(
        polygons, vertices, connectivity, centres, lines, mesh_crs=CRS, geometry_crs=CRS, **kwargs
    )


def _cells(mask: np.ndarray) -> set[tuple[int, int]]:
    return {tuple(int(v) for v in divmod(int(i), N)) for i in np.flatnonzero(mask)}


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * RES, (row + 0.5) * RES)


def _small_grid():
    vertices, connectivity = quad_mesh(4, 4, cell_size=75.0)
    rows, cols = np.divmod(np.arange(16), 4)
    centres = np.column_stack([(cols + 0.5) * 75.0, (rows + 0.5) * 75.0])
    return vertices, connectivity, centres, cell_polygons(vertices, connectivity)


def test_short_reach_off_the_mesh() -> None:
    # 8 m across the bottom border, 10 m from the corner: no median is crossed
    # and the midpoint lies 1 m below the grid.
    reach = LineString([(10.0, -5.0), (10.0, 3.0)])

    result = _crossing([reach], grid=_small_grid())

    assert np.flatnonzero(result.mask).tolist() == [0]
    assert result.n_fallback_parts == 1
    assert result.n_outside_parts == 0


def test_no_usable_cell() -> None:
    vertices, connectivity, centres, polygons = _small_grid()
    centres = np.full_like(centres, np.nan)
    reach = LineString([(10.0, 10.0), (200.0, 200.0)])

    result = _crossing([reach], grid=(vertices, connectivity, centres, polygons))

    assert not result.mask.any()
    assert result.n_outside_parts == 1


def test_multi_part_line() -> None:
    long = LineString([_centre(3, 3), _centre(3, 9)])
    short = LineString([(151.0, 151.0), (154.0, 153.0)])

    result = _crossing([MultiLineString([long, short])])

    assert result.n_fallback_parts == 1
    assert (15, 15) in _cells(result.mask)


def test_active_applied_last() -> None:
    line = LineString([_centre(5, 2), _centre(5, 8)])
    active = np.ones(N * N, dtype=bool)
    active[5 * N + 4] = False

    result = _crossing([line], active=active)

    assert _cells(result.mask) == {(5, col) for col in range(2, 9) if col != 4}


def test_polygon_refused() -> None:
    with pytest.raises(ValueError, match="rasterizes lines"):
        _crossing([Point(5.0, 5.0).buffer(3.0)])


NAN_PADDED = np.array([[0.0, 1.0, 5.0, 4.0], [1.0, 2.0, 5.0, np.nan]])
"""A quad and a triangle sharing the edge x = 100, as a stored table padded with NaN reads."""

STRIP_NODES = np.array(
    [
        [0.0, 0.0],
        [100.0, 0.0],
        [200.0, 0.0],
        [300.0, 0.0],
        [0.0, 100.0],
        [100.0, 100.0],
        [200.0, 100.0],
    ]
)


def test_one_centre_per_cell() -> None:
    vertices, connectivity, centres, polygons = _small_grid()

    with pytest.raises(ValueError, match="centres holds 15 point\\(s\\) for 16 cell polygon"):
        line_crossing_cell_mask(
            polygons, vertices, connectivity, centres[:-1], [], mesh_crs=CRS, geometry_crs=CRS
        )


def test_nan_padded_table() -> None:
    polygons = cell_polygons(STRIP_NODES, NAN_PADDED)
    centres = np.array([[50.0, 50.0], [400.0 / 3.0, 100.0 / 3.0]])
    line = LineString([(100.0, 10.0), (100.0, 90.0)])

    result = line_crossing_cell_mask(
        polygons, STRIP_NODES, NAN_PADDED, centres, [line], mesh_crs=CRS, geometry_crs=CRS
    )

    assert result.mask.tolist() == [True, True]
    assert result.n_fallback_parts == 0


def test_one_cell_half_medians() -> None:
    vertices, connectivity = _quad_grid(n=1)
    polygons = cell_polygons(vertices, connectivity)

    result = line_crossing_cell_mask(
        polygons,
        vertices,
        connectivity,
        np.array([[50.0, 50.0]]),
        [LineString([(20.0, 10.0), (20.0, 90.0)])],
        mesh_crs=CRS,
        geometry_crs=CRS,
    )

    assert result.mask.tolist() == [True]
    assert result.n_fallback_parts == 0


def test_no_face_nodes() -> None:
    vertices, connectivity, centres, polygons = _small_grid()
    no_faces = np.full_like(connectivity, -1)
    reach = LineString([(10.0, 10.0), (200.0, 200.0)])

    result = line_crossing_cell_mask(
        polygons, vertices, no_faces, centres, [reach], mesh_crs=CRS, geometry_crs=CRS
    )

    assert np.flatnonzero(result.mask).tolist() == [1 * 4 + 1]
    assert result.n_fallback_parts == 1
