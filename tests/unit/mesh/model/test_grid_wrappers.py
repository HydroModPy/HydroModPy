"""The regular grid of a DEM: its box, its cells and its quad mesh."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid
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
