"""A cell weighs by the share of its area inside an areal layer (D08, GSFLOW overlay).

The centroid rule of :func:`vector_cell_mask` counts a boundary cell whole or
not at all. :func:`cell_area_fraction` gives it the share of its area inside the
polygon, so a cell field summed with these weights is its integral over the
polygon, exactly, whatever the mesh.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box
from shapely.ops import transform

from hydromodpy.spatial.mesh.ops.vector_cell_mask import (
    cell_area_fraction,
    cell_polygons,
    vector_cell_mask,
)

_LAMBERT = "EPSG:2154"


def _quad_grid(*, size: float = 100.0, n: int = 3, x0: float = 0.0, y0: float = 0.0):
    """Return (vertices, connectivity) for an ``n x n`` quad grid, cell id = row * n + col."""
    xs = x0 + size * np.arange(n + 1)
    ys = y0 + size * np.arange(n + 1)
    vertices = np.asarray([(x, y) for y in ys for x in xs], dtype=float)
    rows = []
    for row in range(n):
        for col in range(n):
            a = row * (n + 1) + col
            rows.append([a, a + 1, a + n + 2, a + n + 1])
    return vertices, np.asarray(rows, dtype=int)


def _fraction(vertices, connectivity, geometries, **kwargs) -> np.ndarray:
    return cell_area_fraction(
        cell_polygons(vertices, connectivity),
        geometries,
        mesh_crs=kwargs.pop("mesh_crs", _LAMBERT),
        geometry_crs=kwargs.pop("geometry_crs", _LAMBERT),
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
        polygons, [polygon], mesh_crs=_LAMBERT, geometry_crs=_LAMBERT, rule="centroid"
    )

    assert float((areas * fraction).sum()) == pytest.approx(polygon.area, rel=1e-12)
    assert abs(float(areas[centroid].sum()) - polygon.area) > 1.0
    cut = (fraction > 0.0) & (fraction < 1.0)
    assert cut.any()
    np.testing.assert_array_equal(fraction == 1.0, centroid & ~cut)


def test_a_polygon_in_another_frame_is_projected_before_the_overlay() -> None:
    from pyproj import Transformer

    vertices, connectivity = _quad_grid(size=1000.0, n=2, x0=700000.0, y0=6600000.0)
    to_wgs84 = Transformer.from_crs(_LAMBERT, "EPSG:4326", always_xy=True).transform
    lambert = box(700000.0, 6600000.0, 701000.0, 6602000.0)
    wgs84 = transform(to_wgs84, lambert)

    fraction = _fraction(vertices, connectivity, [wgs84], geometry_crs="EPSG:4326")

    np.testing.assert_allclose(fraction, [1.0, 0.0, 1.0, 0.0], atol=1e-4)


def test_a_degenerate_cell_and_an_empty_layer_weigh_nothing() -> None:
    vertices, connectivity = _quad_grid(n=2)
    polygons = cell_polygons(vertices, connectivity)
    polygons[3] = None

    fraction = cell_area_fraction(
        polygons, [box(-1.0, -1.0, 500.0, 500.0)], mesh_crs=_LAMBERT, geometry_crs=_LAMBERT
    )
    empty = cell_area_fraction(polygons, [], mesh_crs=_LAMBERT, geometry_crs=_LAMBERT)

    np.testing.assert_array_equal(fraction, [1.0, 1.0, 1.0, 0.0])
    np.testing.assert_array_equal(empty, np.zeros(4))


def test_a_missing_frame_is_refused_rather_than_guessed() -> None:
    vertices, connectivity = _quad_grid(n=2)

    with pytest.raises(ValueError, match="explicit mesh_crs"):
        _fraction(vertices, connectivity, [box(0.0, 0.0, 50.0, 50.0)], mesh_crs=None)
