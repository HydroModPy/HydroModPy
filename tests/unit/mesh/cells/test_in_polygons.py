"""A vector layer projected onto mesh cells, by touch, by centre or by area share.

A linework reaches every cell its geometry touches, an areal layer the cells
whose centre it holds (``vector_cell_mask``). A cell weighs by the share of its
area inside an areal layer (``cell_area_fraction``, D08, the GSFLOW overlay):
the centroid rule counts a boundary cell whole or not at all, the share gives
it the part of its area inside the polygon, so a cell field summed with these
weights is its integral over the polygon, exactly, whatever the mesh.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from hypothesis import given, settings
from hypothesis import strategies as st
from shapely.geometry import LineString, Polygon, box
from shapely.ops import transform

from hydromodpy.spatial.mesh.cells.in_polygons import cell_area_fraction, vector_cell_mask
from hydromodpy.spatial.mesh.model.geometry import cell_polygons
from tests._helpers.mesh_cases import LAMBERT93_WKT, regular_mesh

CRS = LAMBERT93_WKT


def _quad_grid(*, x0: float = 0.0, y0: float = 0.0, size: float = 100.0, n: int = 3):
    """Return (vertices, connectivity) of an ``n x n`` grid of ``size`` m cells, row 0 north."""
    mesh = regular_mesh(n, n, dx=size, xmin=x0, ymin=y0).mesh
    return mesh.vertices, mesh.flat_connectivity


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


def test_a_mesh_with_no_usable_cell_reaches_nothing() -> None:
    polygons = np.array([None, None], dtype=object)
    layer = [box(0.0, 0.0, 100.0, 100.0)]

    assert not vector_cell_mask(polygons, layer, mesh_crs=CRS, geometry_crs=CRS).any()
    assert not cell_area_fraction(polygons, layer, mesh_crs=CRS, geometry_crs=CRS).any()


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
