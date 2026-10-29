"""Points sampled inside one cell, :mod:`hydromodpy.spatial.field.cell_sampling`."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely

from hydromodpy.spatial.field.cell_sampling import sample_points_in_cell

L_SHAPE = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 3], [0, 3]]


def _cell(kind: str, vertices) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, vertices=np.asarray(vertices, dtype=float))


@pytest.mark.parametrize(
    ("kind", "vertices", "n_points"),
    [
        ("quadrilateral", [[0, 0], [2, 0], [3, 2], [0, 1]], 36),
        ("triangle", [[0, 0], [3, 0], [0, 2]], 15),
        ("polygon", L_SHAPE, None),
        ("polygon", [[0, 0], [1, 0], [2, 0], [2, 2], [0, 2]], None),
    ],
    ids=["quadrilateral", "triangle", "concave-polygon", "polygon-with-a-flat-corner"],
)
def test_the_samples_lie_in_the_cell_and_spread_with_its_area(kind, vertices, n_points):
    x, y = sample_points_in_cell(_cell(kind, vertices), n_sub_per_axis=6)

    cell = shapely.Polygon(vertices)
    assert shapely.contains_xy(cell, x, y).all()
    if n_points is not None:
        assert x.size == n_points
    left = x < cell.centroid.x
    share = shapely.clip_by_rect(cell, -9, -9, cell.centroid.x, 9).area / cell.area
    assert left.mean() == pytest.approx(share, abs=0.15)


@pytest.mark.parametrize(
    ("vertices", "expected"),
    [([[0, 0], [2, 2]], ([0.0, 2.0], [0.0, 2.0])), ([[0, 0], [1, 1], [2, 2], [3, 3]], ([1.5], [1.5]))],
    ids=["two-vertices", "collinear"],
)  # fmt: skip
def test_a_polygon_without_area_gives_its_vertices_or_its_centroid(vertices, expected):
    x, y = sample_points_in_cell(_cell("polygon", vertices), n_sub_per_axis=4)
    np.testing.assert_allclose((x, y), expected)
    with pytest.raises(ValueError, match="Unsupported cell kind 'hexagon'"):
        sample_points_in_cell(_cell("hexagon", L_SHAPE), n_sub_per_axis=4)
