"""Cell centres of a structured grid put row 0 at the north.

MODFLOW and FloPy order rows from north to south, and ``yoffset`` is the
lower-left corner. A ``SolverMesh`` carries no ``xcellcenters``, so the
``delr``/``delc`` fallback must follow the same order as ``cell_centroids``.
"""

from __future__ import annotations

import types

import numpy as np
import pytest
from flopy.discretization import StructuredGrid

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import (
    cell_centers_from_sgrid,
)

pytestmark = pytest.mark.fast

NROW, NCOL = 3, 2
DELR = np.array([10.0, 20.0])
DELC = np.array([5.0, 10.0, 15.0])
XOFF, YOFF = 1000.0, 2000.0


def _flopy_grid() -> StructuredGrid:
    return StructuredGrid(
        delc=DELC,
        delr=DELR,
        top=np.zeros((NROW, NCOL)),
        botm=np.full((1, NROW, NCOL), -10.0),
        xoff=XOFF,
        yoff=YOFF,
        nlay=1,
        nrow=NROW,
        ncol=NCOL,
    )


def _solver_mesh(sgrid: StructuredGrid) -> SolverMesh:
    return SolverMesh.from_sgrid(
        sgrid,
        zbot=np.asarray(sgrid.botm, dtype=float),
        inactive_mask=np.zeros((NROW, NCOL), dtype=bool),
    )


def test_a_solver_mesh_gets_the_centres_of_its_own_cells():
    mesh = _solver_mesh(_flopy_grid())
    x, y = cell_centers_from_sgrid(mesh, NROW, NCOL)
    expected = mesh.cell_centroids().reshape(NROW, NCOL, 2)
    np.testing.assert_allclose(x, expected[..., 0])
    np.testing.assert_allclose(y, expected[..., 1])


def test_row_zero_is_the_north_row():
    mesh = _solver_mesh(_flopy_grid())
    _, y = cell_centers_from_sgrid(mesh, NROW, NCOL)
    assert np.all(np.diff(y[:, 0]) < 0.0)
    assert y[0, 0] == pytest.approx(YOFF + DELC.sum() - DELC[0] / 2.0)
    assert y[-1, 0] == pytest.approx(YOFF + DELC[-1] / 2.0)


def test_the_delr_delc_fallback_matches_the_flopy_centres():
    grid = _flopy_grid()
    bare = types.SimpleNamespace(delr=DELR, delc=DELC, xoffset=grid.xoffset, yoffset=grid.yoffset)
    x_flopy, y_flopy = cell_centers_from_sgrid(grid, NROW, NCOL)
    x_bare, y_bare = cell_centers_from_sgrid(bare, NROW, NCOL)
    np.testing.assert_allclose(x_bare, x_flopy)
    np.testing.assert_allclose(y_bare, y_flopy)


def test_a_mesh_built_from_arrays_follows_the_same_row_order():
    from_arrays = SolverMesh.from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=np.zeros((NROW, NCOL)),
        botm=np.full((1, NROW, NCOL), -10.0),
        dx=10.0,
        dy=10.0,
        xoff=XOFF,
        yoff=YOFF,
    )
    x, y = cell_centers_from_sgrid(from_arrays, NROW, NCOL)
    expected = from_arrays.cell_centroids().reshape(NROW, NCOL, 2)
    np.testing.assert_allclose(x, expected[..., 0])
    np.testing.assert_allclose(y, expected[..., 1])
    assert np.all(np.diff(y[:, 0]) < 0.0)
