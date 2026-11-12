"""A mapped network drawn on mesh cells as WhiteboxTools VectorLinesToRaster draws it.

Abherve et al. (2023) rasterize the mapped network of the stream criterion with
``VectorLinesToRaster``. Its source marks a cell when the line crosses one of the two
medians of that cell: a thin line, neither Bresenham nor all-touched. The medians of a
grid are the segments joining the centers of edge-sharing cells, which is how
``line_crossing_cell_mask`` states the rule on any mesh. The oracle below is the two
loops of the Rust source, ported line for line.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box

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


def _whitebox_oracle(line: LineString) -> np.ndarray:
    """VectorLinesToRaster on a y-up grid: rows cut at center ordinates, columns at abscissas."""
    mask = np.zeros(N * N, dtype=bool)

    def between(value: float, a: float, b: float) -> bool:
        return value == a or value == b or min(a, b) < value < max(a, b)

    coords = np.asarray(line.coords)[:, :2]
    for (xa, ya), (xb, yb) in zip(coords[:-1], coords[1:], strict=True):
        for row in range(max(int(min(ya, yb) // RES), 0), min(int(max(ya, yb) // RES), N - 1) + 1):
            yc = (row + 0.5) * RES
            if yb != ya and between(yc, ya, yb):
                col = int(math.floor((xa + (yc - ya) / (yb - ya) * (xb - xa)) / RES))
                if 0 <= col < N:
                    mask[row * N + col] = True
        for col in range(max(int(min(xa, xb) // RES), 0), min(int(max(xa, xb) // RES), N - 1) + 1):
            xc = (col + 0.5) * RES
            if xb != xa and between(xc, xa, xb):
                row = int(math.floor((ya + (xc - xa) / (xb - xa) * (yb - ya)) / RES))
                if 0 <= row < N:
                    mask[row * N + col] = True
    return mask


def _random_polylines(count: int, seed: int = 20260927) -> list[LineString]:
    rng = np.random.default_rng(seed)
    lines = []
    while len(lines) < count:
        n_vertices = int(rng.integers(2, 9))
        start = rng.uniform(0.0, N * RES, size=2)
        steps = rng.normal(0.0, 3.0 * RES, size=(n_vertices - 1, 2))
        coords = np.clip(np.vstack([start, start + np.cumsum(steps, axis=0)]), 1e-3, N * RES - 1e-3)
        line = LineString(coords)
        if line.length > 3.0 * RES:
            lines.append(line)
    return lines


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * RES, (row + 0.5) * RES)


def _small_grid():
    vertices, connectivity = quad_mesh(4, 4, cell_size=75.0)
    rows, cols = np.divmod(np.arange(16), 4)
    centres = np.column_stack([(cols + 0.5) * 75.0, (rows + 0.5) * 75.0])
    return vertices, connectivity, centres, cell_polygons(vertices, connectivity)


def test_a_short_reach_whose_midpoint_is_off_the_mesh_keeps_the_cell_it_enters() -> None:
    # 8 m across the bottom border, 10 m from the corner: no median is crossed
    # and the midpoint lies 1 m below the grid.
    reach = LineString([(10.0, -5.0), (10.0, 3.0)])

    result = _crossing([reach], grid=_small_grid())

    assert np.flatnonzero(result.mask).tolist() == [0]
    assert result.n_fallback_parts == 1
    assert result.n_outside_parts == 0


def test_a_mesh_with_no_usable_cell_counts_every_part_outside() -> None:
    vertices, connectivity, centres, polygons = _small_grid()
    centres = np.full_like(centres, np.nan)
    reach = LineString([(10.0, 10.0), (200.0, 200.0)])

    result = _crossing([reach], grid=(vertices, connectivity, centres, polygons))

    assert not result.mask.any()
    assert result.n_outside_parts == 1


def test_multi_part_lines_are_split_and_each_part_counts() -> None:
    long = LineString([_centre(3, 3), _centre(3, 9)])
    short = LineString([(151.0, 151.0), (154.0, 153.0)])

    result = _crossing([MultiLineString([long, short])])

    assert result.n_fallback_parts == 1
    assert (15, 15) in _cells(result.mask)


def test_active_is_applied_last() -> None:
    line = LineString([_centre(5, 2), _centre(5, 8)])
    active = np.ones(N * N, dtype=bool)
    active[5 * N + 4] = False

    result = _crossing([line], active=active)

    assert _cells(result.mask) == {(5, col) for col in range(2, 9) if col != 4}


def test_a_polygon_layer_is_refused() -> None:
    with pytest.raises(ValueError, match="rasterizes lines"):
        _crossing([Point(5.0, 5.0).buffer(3.0)])


def _voronoi_mesh(seed: int = 7):
    """A bounded Voronoi mesh: generator seeds as centers, ragged connectivity."""
    from shapely import voronoi_polygons
    from shapely.geometry import MultiPoint

    rng = np.random.default_rng(seed)
    seeds = rng.uniform(0.0, 400.0, size=(300, 2))
    frame = box(0.0, 0.0, 400.0, 400.0)
    cells = voronoi_polygons(MultiPoint(seeds), extend_to=frame)
    by_seed = {}
    for cell in cells.geoms:
        clipped = cell.intersection(frame)
        inside = [k for k, s in enumerate(seeds) if clipped.contains(Point(s))]
        by_seed[inside[0]] = clipped
    node_index: dict[tuple[float, float], int] = {}
    rows = []
    for k in range(len(seeds)):
        ring = [
            node_index.setdefault((round(x, 6), round(y, 6)), len(node_index))
            for x, y in list(by_seed[k].exterior.coords)[:-1]
        ]
        rows.append(np.asarray(ring))
    vertices = np.zeros((len(node_index), 2))
    for (x, y), index in node_index.items():
        vertices[index] = (x, y)
    polygons = np.asarray(
        [Polygon(vertices[row]) for row in rows],
        dtype=object,
    )
    return vertices, rows, seeds, polygons


def _dense(rows: list[np.ndarray]) -> np.ndarray:
    table = np.full((len(rows), max(len(row) for row in rows)), -1, dtype=int)
    for index, row in enumerate(rows):
        table[index, : len(row)] = row
    return table


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


def test_the_crossing_rule_needs_one_centre_per_cell() -> None:
    vertices, connectivity, centres, polygons = _small_grid()

    with pytest.raises(ValueError, match="centres holds 15 point\\(s\\) for 16 cell polygon"):
        line_crossing_cell_mask(
            polygons, vertices, connectivity, centres[:-1], [], mesh_crs=CRS, geometry_crs=CRS
        )


def test_the_crossing_rule_reads_a_table_padded_with_nan() -> None:
    polygons = cell_polygons(STRIP_NODES, NAN_PADDED)
    centres = np.array([[50.0, 50.0], [400.0 / 3.0, 100.0 / 3.0]])
    line = LineString([(100.0, 10.0), (100.0, 90.0)])

    result = line_crossing_cell_mask(
        polygons, STRIP_NODES, NAN_PADDED, centres, [line], mesh_crs=CRS, geometry_crs=CRS
    )

    assert result.mask.tolist() == [True, True]
    assert result.n_fallback_parts == 0


def test_one_cell_crossed_by_a_reach_draws_its_half_medians() -> None:
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


def test_a_face_table_without_nodes_leaves_every_reach_to_its_midpoint_cell() -> None:
    vertices, connectivity, centres, polygons = _small_grid()
    no_faces = np.full_like(connectivity, -1)
    reach = LineString([(10.0, 10.0), (200.0, 200.0)])

    result = line_crossing_cell_mask(
        polygons, vertices, no_faces, centres, [reach], mesh_crs=CRS, geometry_crs=CRS
    )

    assert np.flatnonzero(result.mask).tolist() == [1 * 4 + 1]
    assert result.n_fallback_parts == 1
