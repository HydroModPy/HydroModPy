"""The regular cell mesh the geology demo maps a property on."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.field.geology.geology_mesh import regular_cell_mesh_over_bounds
from tests._helpers.cell_meshes import TEST_CRS_WKT


def test_the_cells_keep_the_aspect_ratio_of_the_box():
    mesh = regular_cell_mesh_over_bounds(
        (100.0, 200.0, 500.0, 300.0), crs_wkt=TEST_CRS_WKT, target_n_cells=100
    )

    assert mesh.n_cells == 20 * 5
    assert mesh.mesh.bounds() == (100.0, 200.0, 500.0, 300.0)
    np.testing.assert_allclose(mesh.geometry.areas, 400.0)


@pytest.mark.parametrize(
    ("bounds", "reason"),
    [
        ((0.0, 0.0, np.inf, 1.0), "finite values"),
        ((0.0, 1.0, 1.0, 1.0), "ymax > ymin"),
    ],
    ids=["infinite", "flat"],
)
def test_a_box_must_be_finite_and_open(bounds, reason):
    with pytest.raises(ValueError, match=reason):
        regular_cell_mesh_over_bounds(bounds, crs_wkt=TEST_CRS_WKT)
