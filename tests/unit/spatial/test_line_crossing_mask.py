"""The mapped network is drawn as WhiteboxTools VectorLinesToRaster draws it.

Abherve et al. (2023) rasterize the mapped network with ``VectorLinesToRaster``.
Its source marks a cell when the line crosses one of the two medians of that
cell: a thin line, neither Bresenham nor all-touched. The medians of a grid are
the segments joining the centres of edge-sharing cells, which is how
``line_crossing_cell_mask`` states the rule on any mesh. The oracle below is
the two loops of the Rust source, ported line for line.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from hydromodpy.spatial.mesh.ops.vector_cell_mask import (
    cell_polygons,
    line_crossing_cell_mask,
    vector_cell_mask,
)
from tests._helpers.ugrid_meshes import quad_mesh

CRS = "EPSG:2154"
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
    """VectorLinesToRaster on a y-up grid: rows cut at centre ordinates, columns at abscissas."""
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


@pytest.mark.parametrize("line", _random_polylines(200), ids=lambda _: "")
def test_the_rule_is_vector_lines_to_raster_on_a_grid(line: LineString) -> None:
    result = _crossing([line])

    assert result.n_fallback_parts == 0
    assert _cells(result.mask) == _cells(_whitebox_oracle(line))


def test_a_crossing_on_a_cell_edge_marks_both_cells() -> None:
    # The line crosses the median x = 15 exactly on the edge y = 10: WBT picks
    # one side by index order, the rule keeps both.
    result = _crossing([LineString([(12.0, 8.0), (18.0, 12.0)])])

    assert _cells(result.mask) == {(0, 1), (1, 1)}


def test_a_line_lying_on_a_median_marks_the_row_it_runs_along() -> None:
    result = _crossing([LineString([(3.0, 15.0), (37.0, 15.0)])])

    assert _cells(result.mask) == {(1, 0), (1, 1), (1, 2), (1, 3)}


def test_the_half_median_of_a_border_cell_counts() -> None:
    # WBT draws the median up to the raster border; the rule joins a border
    # centre to the midpoint of its outer edge for the same reason.
    result = _crossing([LineString([(2.0, 3.0), (2.0, 7.0)])])

    assert _cells(result.mask) == {(0, 0)}
    assert result.n_fallback_parts == 0


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * RES, (row + 0.5) * RES)


def test_a_diagonal_chain_of_centres_comes_back_as_itself() -> None:
    chain = [(k, k) for k in range(2, 20)]
    line = LineString([_centre(*cell) for cell in chain])

    assert _cells(_crossing([line]).mask) == set(chain)


def test_a_staircase_chain_of_centres_comes_back_as_itself() -> None:
    chain = [(2, 2)]
    for _ in range(8):
        row, col = chain[-1]
        chain += [(row + 1, col), (row + 1, col + 1)]
    line = LineString([_centre(*cell) for cell in chain])

    assert _cells(_crossing([line]).mask) == set(chain)


def test_touch_thickens_the_same_diagonal_chain() -> None:
    """The counter-example behind the default: every diagonal step gains a corner pair."""
    vertices, connectivity, _, polygons = GRID
    chain = [(k, k) for k in range(2, 20)]
    line = LineString([_centre(*cell) for cell in chain])

    touched = _cells(vector_cell_mask(polygons, [line], mesh_crs=CRS, geometry_crs=CRS))

    assert set(chain) < touched
    assert len(touched - set(chain)) == 2 * (len(chain) - 1)


def test_a_reach_that_crosses_no_median_keeps_its_midpoint_cell() -> None:
    # 10 m of stream in the middle of a 75 m cell, the fallback of the rule.
    vertices, connectivity = quad_mesh(4, 4, cell_size=75.0)
    rows, cols = np.divmod(np.arange(16), 4)
    centres = np.column_stack([(cols + 0.5) * 75.0, (rows + 0.5) * 75.0])
    grid = (vertices, connectivity, centres, cell_polygons(vertices, connectivity))
    reach = LineString([(160.0, 100.0), (170.0, 100.0)])

    result = _crossing([reach], grid=grid)

    assert np.flatnonzero(result.mask).tolist() == [1 * 4 + 2]
    assert result.n_fallback_parts == 1


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


def test_a_reach_wholly_off_the_mesh_marks_nothing_and_is_counted() -> None:
    # Snapping it to the nearest border cell would draw a stream the domain lacks.
    reach = LineString([(100.0, -30.0), (110.0, -30.0)])

    result = _crossing([reach], grid=_small_grid())

    assert not result.mask.any()
    assert result.n_fallback_parts == 0
    assert result.n_outside_parts == 1


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
    """A bounded Voronoi mesh: generator seeds as centres, ragged connectivity."""
    from shapely import voronoi_polygons
    from shapely.geometry import MultiPoint, box

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


def test_on_a_voronoi_mesh_the_line_is_a_thinner_subset_of_touch() -> None:
    """Every reach marks cells of its own, none outside the cells it touches.

    Face connectivity is NOT promised for an arbitrary line: where a line only
    clips the corner of a small cell, its two neighbours along the line can
    share neither an edge nor a node. The grid shows the same thing as its
    diagonal steps. What the criterion needs is the next test.
    """
    vertices, rows, seeds, polygons = _voronoi_mesh()
    line = LineString([(20.0, 30.0), (150.0, 210.0), (380.0, 260.0)])

    crossed = line_crossing_cell_mask(
        polygons, vertices, rows, seeds, [line], mesh_crs=CRS, geometry_crs=CRS
    )
    touched = vector_cell_mask(polygons, [line], mesh_crs=CRS, geometry_crs=CRS)

    assert crossed.n_fallback_parts == 0
    assert not (crossed.mask & ~touched).any()
    assert crossed.mask.sum() < touched.sum()


def test_on_a_voronoi_mesh_a_chain_of_seeds_comes_back_as_itself() -> None:
    """The model's own network, drawn through its seeds, is the observed network."""
    from hydromodpy.core.field_routing import cell_adjacency_from_face_connectivity

    vertices, rows, seeds, polygons = _voronoi_mesh()
    adjacency = cell_adjacency_from_face_connectivity(_dense(rows), n_cells=len(rows))
    start = int(np.argmin(np.hypot(*(seeds - (60.0, 60.0)).T)))
    goal = int(np.argmin(np.hypot(*(seeds - (340.0, 330.0)).T)))
    previous = {start: -1}
    frontier = [start]
    while goal not in previous:
        frontier = [
            other
            for cell in frontier
            for other in sorted(adjacency[cell])
            if other not in previous and previous.setdefault(other, cell) == cell
        ]
    chain = [goal]
    while previous[chain[-1]] != -1:
        chain.append(previous[chain[-1]])

    crossed = line_crossing_cell_mask(
        polygons,
        vertices,
        rows,
        seeds,
        [LineString(seeds[chain])],
        mesh_crs=CRS,
        geometry_crs=CRS,
    )

    assert set(np.flatnonzero(crossed.mask).tolist()) == set(chain)
