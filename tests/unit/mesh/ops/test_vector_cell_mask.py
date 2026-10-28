"""A vector layer projected onto mesh cells, by touch, by centre, by area share or by crossing.

A linework reaches every cell its geometry touches, an areal layer the cells
whose centre it holds (``vector_cell_mask``). A cell weighs by the share of its
area inside an areal layer (``cell_area_fraction``, D08, the GSFLOW overlay):
the centroid rule counts a boundary cell whole or not at all, the share gives
it the part of its area inside the polygon, so a cell field summed with these
weights is its integral over the polygon, exactly, whatever the mesh.

The mapped network of the stream criterion is drawn as WhiteboxTools
VectorLinesToRaster draws it (``line_crossing_cell_mask``). Abherve et al.
(2023) rasterize the mapped network with ``VectorLinesToRaster``. Its source
marks a cell when the line crosses one of the two medians of that cell: a thin
line, neither Bresenham nor all-touched. The medians of a grid are the segments
joining the centres of edge-sharing cells, which is how
``line_crossing_cell_mask`` states the rule on any mesh. The oracle below is the
two loops of the Rust source, ported line for line.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import shapely
from hypothesis import given, settings
from hypothesis import strategies as st
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    Point,
    Polygon,
    box,
)
from shapely.ops import transform

from hydromodpy.spatial.mesh.model.derived_geometry import cell_polygons
from hydromodpy.spatial.mesh.ops.vector_cell_mask import (
    cell_area_fraction,
    line_crossing_cell_mask,
    vector_cell_mask,
)
from tests._helpers.mesh_cases import LAMBERT93_WKT, regular_mesh
from tests._helpers.ugrid_meshes import quad_mesh

CRS = LAMBERT93_WKT


def _quad_grid(*, x0: float = 0.0, y0: float = 0.0, size: float = 100.0, n: int = 3):
    """Return (vertices, connectivity) of an ``n x n`` grid of ``size`` m cells, row 0 north."""
    mesh = regular_mesh(n, n, dx=size, xmin=x0, ymin=y0).mesh
    return mesh.vertices, mesh.flat_connectivity


# -- touch and centre masks ----------------------------------------------------


def _mask(vertices, connectivity, geometries, **kwargs) -> np.ndarray:
    return vector_cell_mask(
        cell_polygons(vertices, connectivity),
        geometries,
        mesh_crs=kwargs.pop("mesh_crs", CRS),
        geometry_crs=kwargs.pop("geometry_crs", CRS),
        **kwargs,
    )


def test_line_marks_every_cell_it_crosses():
    vertices, connectivity = _quad_grid()
    line = LineString([(150.0, 10.0), (150.0, 290.0)])

    mask = _mask(vertices, connectivity, [line])

    assert np.flatnonzero(mask).tolist() == [1, 4, 7]


def test_line_on_a_shared_edge_marks_both_neighbours():
    # The whole point of the intersects rule: a linework running along a cell
    # boundary belongs to both cells. A centroid rule would keep neither.
    vertices, connectivity = _quad_grid()
    line = LineString([(100.0, 150.0), (100.0, 160.0)])

    mask = _mask(vertices, connectivity, [line])

    assert np.flatnonzero(mask).tolist() == [3, 4]


def test_empty_geometry_set_gives_an_empty_mask():
    vertices, connectivity = _quad_grid()

    mask = _mask(vertices, connectivity, [])

    assert mask.shape == (9,)
    assert not mask.any()


def test_ragged_connectivity_is_accepted():
    # Cell 0 is a triangle, cell 1 a pentagon: the mask must not assume arity.
    vertices = np.asarray(
        [
            (0.0, 0.0),
            (10.0, 0.0),
            (0.0, 10.0),
            (20.0, 0.0),
            (30.0, 0.0),
            (30.0, 10.0),
            (25.0, 15.0),
            (20.0, 10.0),
        ],
        dtype=float,
    )
    connectivity = (
        np.asarray([0, 1, 2], dtype=int),
        np.asarray([3, 4, 5, 6, 7], dtype=int),
    )

    mask = _mask(vertices, connectivity, [LineString([(24.0, 5.0), (28.0, 5.0)])])

    assert mask.tolist() == [False, True]


def test_degenerate_cell_is_never_in_the_mask():
    vertices, connectivity = _quad_grid(n=1)
    degenerate = np.full((2, 4), -1, dtype=int)
    degenerate[0] = connectivity[0]
    degenerate[1, :2] = connectivity[0][:2]

    mask = _mask(vertices, degenerate, [LineString([(10.0, 10.0), (90.0, 90.0)])])

    assert mask.tolist() == [True, False]


def test_distance_widens_the_mask_and_leaves_the_input_geometry_alone():
    vertices, connectivity = _quad_grid()
    line = LineString([(150.0, 140.0), (150.0, 160.0)])

    tight = _mask(vertices, connectivity, [line])
    # 45 m reaches the two cells 40 m away along y, not the ones 50 m away along x.
    wide = _mask(vertices, connectivity, [line], distance_m=45.0)

    assert np.flatnonzero(tight).tolist() == [4]
    assert np.flatnonzero(wide).tolist() == [1, 4, 7]
    # dwithin, not a buffer: the caller's geometry is the one it passed in.
    assert line.equals(LineString([(150.0, 140.0), (150.0, 160.0)]))


def test_geometries_are_reprojected_into_the_mesh_frame():
    from pyproj import Transformer
    from shapely.ops import transform

    vertices, connectivity = _quad_grid(x0=300_000.0, y0=6_800_000.0)
    line = LineString([(300_150.0, 6_800_110.0), (300_150.0, 6_800_190.0)])
    to_wgs84 = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    line_wgs84 = transform(to_wgs84, line)

    reprojected = _mask(vertices, connectivity, [line_wgs84], geometry_crs="EPSG:4326")
    native = _mask(vertices, connectivity, [line])

    assert np.flatnonzero(reprojected).tolist() == [4]
    assert reprojected.tolist() == native.tolist()


def test_mislabelled_geometry_crs_finds_nothing():
    # Control for the test above: degrees read as metres land nowhere near the mesh.
    from pyproj import Transformer
    from shapely.ops import transform

    vertices, connectivity = _quad_grid(x0=300_000.0, y0=6_800_000.0)
    to_wgs84 = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    line_wgs84 = transform(
        to_wgs84, LineString([(300_150.0, 6_800_110.0), (300_150.0, 6_800_190.0)])
    )

    mask = _mask(vertices, connectivity, [line_wgs84], geometry_crs=CRS)

    assert not mask.any()


@pytest.mark.parametrize("missing", ["mesh_crs", "geometry_crs"])
def test_a_missing_crs_raises(missing):
    vertices, connectivity = _quad_grid()
    crs = {"mesh_crs": CRS, "geometry_crs": CRS, missing: None}

    with pytest.raises(ValueError, match=missing):
        _mask(vertices, connectivity, [LineString([(10.0, 10.0), (20.0, 20.0)])], **crs)


def test_an_areal_layer_by_touch_keeps_a_full_exterior_ring():
    # 3 x 3 grid of 100 m cells; the polygon covers the middle cell exactly.
    vertices, connectivity = _quad_grid()
    middle = Polygon([(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)])

    touched = _mask(vertices, connectivity, [middle])
    centred = _mask(vertices, connectivity, [middle], rule="centroid")

    # Touch takes the whole 3 x 3 block, the eight neighbours sharing an edge
    # or a corner with the polygon boundary. The centroid rule takes the one
    # cell the polygon really covers.
    assert touched.sum() == 9
    assert np.flatnonzero(centred).tolist() == [4]


def test_the_centroid_rule_keeps_a_cell_straddling_the_boundary_by_its_centre():
    vertices, connectivity = _quad_grid()
    # The polygon covers the left 60 m of the middle column, so the centre of
    # the middle cell (150, 150) is inside while most of its area is not.
    polygon = Polygon([(100.0, 100.0), (160.0, 100.0), (160.0, 200.0), (100.0, 200.0)])
    centred = _mask(vertices, connectivity, [polygon], rule="centroid")
    assert np.flatnonzero(centred).tolist() == [4]

    # Shifted so the centre falls outside, the same overlap is dropped.
    outside = Polygon([(100.0, 100.0), (140.0, 100.0), (140.0, 200.0), (100.0, 200.0)])
    assert not _mask(vertices, connectivity, [outside], rule="centroid").any()


def test_a_linework_would_lose_half_its_cells_under_the_centroid_rule():
    vertices, connectivity = _quad_grid()
    line = LineString([(10.0, 150.0), (290.0, 150.0)])
    assert _mask(vertices, connectivity, [line]).sum() == 3
    # The line runs through the cell centres of the middle row here, but a line
    # that does not is dropped entirely, which is why touch is the linework rule.
    off_centre = LineString([(10.0, 190.0), (290.0, 190.0)])
    assert _mask(vertices, connectivity, [off_centre]).sum() == 3
    assert not _mask(vertices, connectivity, [off_centre], rule="centroid").any()


def test_the_two_rules_cannot_be_combined():
    vertices, connectivity = _quad_grid()
    polygon = Polygon([(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)])
    with pytest.raises(ValueError, match="two different masks"):
        _mask(vertices, connectivity, [polygon], rule="centroid", distance_m=50.0)


def test_an_unknown_rule_is_refused_by_name():
    vertices, connectivity = _quad_grid()
    with pytest.raises(ValueError, match="rule must be"):
        _mask(vertices, connectivity, [], rule="nearest")


# -- area share ---------------------------------------------------------------


def _fraction(vertices, connectivity, geometries, **kwargs) -> np.ndarray:
    return cell_area_fraction(
        cell_polygons(vertices, connectivity),
        geometries,
        mesh_crs=kwargs.pop("mesh_crs", CRS),
        geometry_crs=kwargs.pop("geometry_crs", CRS),
    )


def test_inside_cells_weigh_one_outside_zero_and_cut_cells_their_share() -> None:
    vertices, connectivity = _quad_grid()
    # Covers the left column, a quarter of the middle column, nothing on the right.
    polygon = box(0.0, 0.0, 125.0, 300.0)

    fraction = _fraction(vertices, connectivity, [polygon])

    np.testing.assert_allclose(fraction.reshape(3, 3), [[1.0, 0.25, 0.0]] * 3)


def test_the_weighted_areas_sum_to_the_polygon_area_where_the_centroid_mask_does_not() -> None:
    vertices, connectivity = _quad_grid(size=10.0, n=40, x0=-200.0, y0=-200.0)
    angles = np.linspace(0.0, 2.0 * np.pi, 400, endpoint=False)
    radius = 150.0 * (1.0 + 0.1 * np.sin(5.0 * angles))
    polygon = Polygon(np.c_[radius * np.cos(angles) + 3.0, radius * np.sin(angles) - 4.0])
    polygons = cell_polygons(vertices, connectivity)
    areas = shapely.area(polygons)

    fraction = _fraction(vertices, connectivity, [polygon])
    centroid = vector_cell_mask(
        polygons, [polygon], mesh_crs=CRS, geometry_crs=CRS, rule="centroid"
    )

    assert float((areas * fraction).sum()) == pytest.approx(polygon.area, rel=1e-12)
    assert abs(float(areas[centroid].sum()) - polygon.area) > 1.0
    cut = (fraction > 0.0) & (fraction < 1.0)
    assert cut.any()
    np.testing.assert_array_equal(fraction == 1.0, centroid & ~cut)


def test_a_polygon_in_another_frame_is_projected_before_the_overlay() -> None:
    from pyproj import Transformer

    vertices, connectivity = _quad_grid(size=1000.0, n=2, x0=700000.0, y0=6600000.0)
    to_wgs84 = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    lambert = box(700000.0, 6600000.0, 701000.0, 6602000.0)
    wgs84 = transform(to_wgs84, lambert)

    fraction = _fraction(vertices, connectivity, [wgs84], geometry_crs="EPSG:4326")

    np.testing.assert_allclose(fraction, [1.0, 0.0, 1.0, 0.0], atol=1e-4)


def test_a_degenerate_cell_and_an_empty_layer_weigh_nothing() -> None:
    vertices, connectivity = _quad_grid(n=2)
    polygons = cell_polygons(vertices, connectivity)
    polygons[3] = None

    fraction = cell_area_fraction(
        polygons, [box(-1.0, -1.0, 500.0, 500.0)], mesh_crs=CRS, geometry_crs=CRS
    )
    empty = cell_area_fraction(polygons, [], mesh_crs=CRS, geometry_crs=CRS)

    np.testing.assert_array_equal(fraction, [1.0, 1.0, 1.0, 0.0])
    np.testing.assert_array_equal(empty, np.zeros(4))


def test_a_missing_frame_is_refused_rather_than_guessed() -> None:
    vertices, connectivity = _quad_grid(n=2)

    with pytest.raises(ValueError, match="explicit mesh_crs"):
        _fraction(vertices, connectivity, [box(0.0, 0.0, 50.0, 50.0)], mesh_crs=None)


# -- crossing rule ------------------------------------------------------------

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


def _small_grid():
    vertices, connectivity = quad_mesh(4, 4, cell_size=75.0)
    rows, cols = np.divmod(np.arange(16), 4)
    centres = np.column_stack([(cols + 0.5) * 75.0, (rows + 0.5) * 75.0])
    return vertices, connectivity, centres, cell_polygons(vertices, connectivity)


def test_a_reach_that_crosses_no_median_keeps_its_midpoint_cell() -> None:
    # 10 m of stream in the middle of a 75 m cell, the fallback of the rule.
    reach = LineString([(160.0, 100.0), (170.0, 100.0)])

    result = _crossing([reach], grid=_small_grid())

    assert np.flatnonzero(result.mask).tolist() == [1 * 4 + 2]
    assert result.n_fallback_parts == 1


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


# -- cells and layers a caller may hand over ------------------------------------

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


def test_a_mesh_with_no_usable_cell_reaches_nothing() -> None:
    polygons = np.array([None, None], dtype=object)
    layer = [box(0.0, 0.0, 100.0, 100.0)]

    assert not vector_cell_mask(polygons, layer, mesh_crs=CRS, geometry_crs=CRS).any()
    assert not cell_area_fraction(polygons, layer, mesh_crs=CRS, geometry_crs=CRS).any()


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


def test_lines_nested_in_a_collection_count_and_a_point_length_line_does_not() -> None:
    nested = GeometryCollection(
        [MultiLineString([[_centre(3, 3), _centre(3, 9)], [_centre(8, 3), _centre(8, 9)]])]
    )
    point_like = LineString([_centre(15, 15), _centre(15, 15)])

    result = _crossing([nested, point_like])

    assert _cells(result.mask) == {(row, col) for row in (3, 8) for col in range(3, 10)}
    assert result.n_fallback_parts == 0 and result.n_outside_parts == 0


# -- invariants on random polygons ----------------------------------------------

KM = regular_mesh(10, 10, dx=100.0).mesh
KM_POLYGONS = cell_polygons(KM.vertices, KM.flat_connectivity)


@st.composite
def _star_polygons(draw) -> Polygon:
    """A polygon star-shaped about a centre on the grid, with 3 to 12 corners."""
    cx = draw(st.floats(0.0, 1000.0))
    cy = draw(st.floats(0.0, 1000.0))
    radii = draw(st.lists(st.floats(5.0, 600.0), min_size=3, max_size=12))
    angles = np.linspace(0.0, 2.0 * np.pi, len(radii), endpoint=False)
    return Polygon(np.c_[cx + np.cos(angles) * radii, cy + np.sin(angles) * radii])


@settings(max_examples=50, deadline=None, derandomize=True)
@given(_star_polygons())
def test_the_area_shares_sum_to_the_polygon_inside_the_mesh(polygon: Polygon) -> None:
    fraction = cell_area_fraction(KM_POLYGONS, [polygon], mesh_crs=CRS, geometry_crs=CRS)
    inside = polygon.intersection(box(0.0, 0.0, 1000.0, 1000.0)).area

    assert float((shapely.area(KM_POLYGONS) * fraction).sum()) == pytest.approx(
        inside, rel=1e-9, abs=1e-6
    )
    assert np.all((fraction >= 0.0) & (fraction <= 1.0))


@settings(max_examples=50, deadline=None, derandomize=True)
@given(_star_polygons())
def test_the_centre_and_area_rules_keep_touched_cells_only(polygon: Polygon) -> None:
    def mask(**kwargs) -> np.ndarray:
        return vector_cell_mask(KM_POLYGONS, [polygon], mesh_crs=CRS, geometry_crs=CRS, **kwargs)

    touched = mask()
    centred = mask(rule="centroid")
    fraction = cell_area_fraction(KM_POLYGONS, [polygon], mesh_crs=CRS, geometry_crs=CRS)

    assert not (centred & ~touched).any()
    assert not ((fraction > 0.0) & ~touched).any()
    assert not ((fraction == 1.0) & ~centred).any()
