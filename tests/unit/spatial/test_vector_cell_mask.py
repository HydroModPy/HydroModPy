"""Unit tests for the vector-to-cell projection used by the network criterion."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons, vector_cell_mask

_LAMBERT = "EPSG:2154"


def _quad_grid(*, x0: float = 0.0, y0: float = 0.0, size: float = 100.0, n: int = 3):
    """Return (vertices, connectivity) for an ``n x n`` quad grid, cell id = row * n + col."""
    xs = x0 + size * np.arange(n + 1)
    ys = y0 + size * np.arange(n + 1)
    vertices = np.asarray([(x, y) for y in ys for x in xs], dtype=float)

    def vid(col: int, row: int) -> int:
        return row * (n + 1) + col

    connectivity = np.asarray(
        [
            [vid(col, row), vid(col + 1, row), vid(col + 1, row + 1), vid(col, row + 1)]
            for row in range(n)
            for col in range(n)
        ],
        dtype=int,
    )
    return vertices, connectivity


def _mask(vertices, connectivity, geometries, **kwargs) -> np.ndarray:
    return vector_cell_mask(
        cell_polygons(vertices, connectivity),
        geometries,
        mesh_crs=kwargs.pop("mesh_crs", _LAMBERT),
        geometry_crs=kwargs.pop("geometry_crs", _LAMBERT),
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


def test_padded_connectivity_ignores_the_negative_nodes():
    vertices, connectivity = _quad_grid(n=1)
    padded = np.full((2, 4), -1, dtype=int)
    padded[0] = connectivity[0]
    padded[1, :3] = connectivity[0][:3]

    polygons = cell_polygons(vertices, padded)

    assert polygons[0].area == pytest.approx(100.0 * 100.0)
    assert polygons[1].area == pytest.approx(0.5 * 100.0 * 100.0)


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
    to_wgs84 = Transformer.from_crs(_LAMBERT, "EPSG:4326", always_xy=True).transform
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
    to_wgs84 = Transformer.from_crs(_LAMBERT, "EPSG:4326", always_xy=True).transform
    line_wgs84 = transform(
        to_wgs84, LineString([(300_150.0, 6_800_110.0), (300_150.0, 6_800_190.0)])
    )

    mask = _mask(vertices, connectivity, [line_wgs84], geometry_crs=_LAMBERT)

    assert not mask.any()


@pytest.mark.parametrize("missing", ["mesh_crs", "geometry_crs"])
def test_a_missing_crs_raises(missing):
    vertices, connectivity = _quad_grid()
    crs = {"mesh_crs": _LAMBERT, "geometry_crs": _LAMBERT, missing: None}

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
