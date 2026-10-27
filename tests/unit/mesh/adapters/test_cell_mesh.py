"""The planar cell mesh of a regular grid."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.adapters.cell_mesh import cell_mesh_from_regular_grid
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import L93_ORIGIN

X0, Y0 = L93_ORIGIN
"""North-west corner of the grid."""


@pytest.fixture
def grid() -> RegularGrid:
    return RegularGrid(shape=(3, 4), dx=25.0, dy=50.0, origin=(X0, Y0))


def test_the_regular_adapter_keeps_the_grid_vertices_and_quads(grid: RegularGrid) -> None:
    cell_mesh = cell_mesh_from_regular_grid(grid, crs_wkt=TEST_CRS_WKT)
    reference = grid.to_hydro_mesh()

    np.testing.assert_array_equal(cell_mesh.mesh.vertices, reference.vertices)
    np.testing.assert_array_equal(cell_mesh.mesh.flat_connectivity, reference.flat_connectivity)
    assert cell_mesh.mesh.flat_connectivity[0].tolist() == [0, 1, 6, 5]
    assert cell_mesh.mesh.flat_connectivity[5].tolist() == [6, 7, 12, 11]
    assert cell_mesh.mesh.vertices[0].tolist() == [X0, Y0]
    assert cell_mesh.structured_shape == (3, 4)
    assert cell_mesh.center_kind == "cell_center"
    assert cell_mesh.identity.engine_id == "regular"
    assert cell_mesh.identity.request_hash == ""
    assert cell_mesh.crs_wkt == TEST_CRS_WKT


def test_the_regular_adapter_centres_are_cell_centres_row_zero_north(grid: RegularGrid) -> None:
    cell_mesh = cell_mesh_from_regular_grid(grid, crs_wkt=TEST_CRS_WKT)

    assert cell_mesh.centers[0].tolist() == [X0 + 12.5, Y0 - 25.0]
    assert cell_mesh.centers[4].tolist() == [X0 + 12.5, Y0 - 75.0]
    np.testing.assert_allclose(cell_mesh.centers, cell_mesh.geometry.area_centroids, atol=1e-6)
    assert cell_mesh.qa.area_sum_rel_error == pytest.approx(0.0, abs=1e-15)
    assert cell_mesh.qa.nonorthogonality_deg["max"] == pytest.approx(0.0, abs=1e-6)
    assert cell_mesh.qa.declarations["deterministic"] is True
