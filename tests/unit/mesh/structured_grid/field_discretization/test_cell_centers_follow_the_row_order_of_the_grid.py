"""A forcing raster lands on the cells of a solver mesh with row 0 at the north.

MODFLOW orders rows from north to south and ``yoff`` is the southern edge. The
forcing reads the centres of the cells (``SolverMesh.cell_centroids``), so a
raster that rises to the north must give a recharge that falls with the row.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.forcing import discretize_fields_on_cells
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

pytestmark = pytest.mark.fast

NROW, NCOL = 3, 2
DX, DY = 10.0, 10.0
XOFF, YOFF = 1000.0, 2000.0
MM_DAY_TO_M_S = 1.0e-3 / 86400.0


def _mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=np.zeros((NROW, NCOL)),
        botm=np.full((1, NROW, NCOL), -10.0),
        dx=DX,
        dy=DY,
        xoff=XOFF,
        yoff=YOFF,
    )


def _northward_raster() -> LoadResult:
    """One pixel per cell, valued by its northing: the value is the pixel's y."""
    x = XOFF + (np.arange(NCOL) + 0.5) * DX
    y = YOFF + (np.arange(NROW)[::-1] + 0.5) * DY
    values = np.repeat(y[:, None], NCOL, axis=1)
    dataset = xr.Dataset({"recharge": (("y", "x"), values)}, coords={"x": x, "y": y})
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=dataset,
        bbox=(XOFF, YOFF, XOFF + NCOL * DX, YOFF + NROW * DY),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def test_the_centres_of_a_mesh_built_from_arrays_put_row_zero_north():
    centers = _mesh().cell_centroids().reshape(NROW, NCOL, 2)
    assert np.all(np.diff(centers[:, 0, 1]) < 0.0)
    assert centers[0, 0, 1] == pytest.approx(YOFF + NROW * DY - DY / 2.0)
    assert centers[-1, 0, 1] == pytest.approx(YOFF + DY / 2.0)
    assert centers[0, 0, 0] == pytest.approx(XOFF + DX / 2.0)


def test_a_raster_that_rises_to_the_north_gives_a_recharge_that_falls_with_the_row():
    mesh = _mesh()
    result = discretize_fields_on_cells(
        load_result=_northward_raster(),
        centers=mesh.cell_centroids(),
        nper=1,
    )
    recharge = result[0].reshape(NROW, NCOL)
    assert np.all(np.diff(recharge[:, 0]) < 0.0)
    northing = mesh.cell_centroids().reshape(NROW, NCOL, 2)[..., 1]
    np.testing.assert_allclose(recharge, northing * MM_DAY_TO_M_S)
