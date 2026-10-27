"""The regular grid of a DEM: its box, its cells, its quad mesh and its planar cell mesh."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.regular_grid import RegularGrid, cell_mesh_from_regular_grid
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import L93_ORIGIN

X0, Y0 = L93_ORIGIN
NROW, NCOL, DX, DY = 3, 4, 25.0, 50.0


@pytest.fixture
def grid() -> RegularGrid:
    """Three rows of four cells whose north-west corner is ``(X0, Y0 + NROW * DY)``."""
    return RegularGrid(shape=(NROW, NCOL), dx=DX, dy=DY, origin=(X0, Y0 + NROW * DY))


def test_a_grid_says_it_is_regular_and_counts_its_cells(grid: RegularGrid) -> None:
    assert grid.topology == "regular"
    assert grid.n_cells == NROW * NCOL


def test_the_box_of_a_grid_runs_south_from_its_origin(grid: RegularGrid) -> None:
    assert grid.bbox == (X0, Y0, X0 + NCOL * DX, Y0 + NROW * DY)


def test_the_mesh_of_a_grid_holds_its_box_and_its_cells(grid: RegularGrid) -> None:
    mesh = grid.to_hydro_mesh()

    xmin, ymin, xmax, ymax = grid.bbox
    assert mesh.bounds() == (xmin, ymin, xmax, ymax)
    assert mesh.n_cells == grid.n_cells
    assert mesh.single_cell_type is CellType.QUADRILATERAL
    assert mesh.structured_shape == grid.shape


def test_cell_zero_is_the_north_west_cell(grid: RegularGrid) -> None:
    mesh = grid.to_hydro_mesh()
    x, y = mesh.cell_centroids()

    assert (x[0], y[0]) == (X0 + 0.5 * DX, Y0 + (NROW - 0.5) * DY)
    np.testing.assert_allclose(np.diff(x[:NCOL]), DX)
    np.testing.assert_allclose(y[::NCOL], Y0 + (NROW - 0.5 - np.arange(NROW)) * DY)


@pytest.fixture
def corner_grid() -> RegularGrid:
    """Three rows of four cells whose north-west corner is ``(X0, Y0)``."""
    return RegularGrid(shape=(3, 4), dx=25.0, dy=50.0, origin=(X0, Y0))


def test_the_regular_adapter_keeps_the_grid_vertices_and_quads(corner_grid: RegularGrid) -> None:
    cell_mesh = cell_mesh_from_regular_grid(corner_grid, crs_wkt=TEST_CRS_WKT)
    reference = corner_grid.to_hydro_mesh()

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


def test_the_regular_adapter_centres_are_cell_centres_row_zero_north(
    corner_grid: RegularGrid,
) -> None:
    cell_mesh = cell_mesh_from_regular_grid(corner_grid, crs_wkt=TEST_CRS_WKT)

    assert cell_mesh.centers[0].tolist() == [X0 + 12.5, Y0 - 25.0]
    assert cell_mesh.centers[4].tolist() == [X0 + 12.5, Y0 - 75.0]
    np.testing.assert_allclose(cell_mesh.centers, cell_mesh.geometry.area_centroids, atol=1e-6)
    assert cell_mesh.qa.area_sum_rel_error == pytest.approx(0.0, abs=1e-15)
    assert cell_mesh.qa.nonorthogonality_deg["max"] == pytest.approx(0.0, abs=1e-6)
    assert cell_mesh.qa.declarations["deterministic"] is True
