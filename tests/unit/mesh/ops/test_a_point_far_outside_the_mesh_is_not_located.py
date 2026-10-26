"""A point outside the mesh takes the nearest cell only within one cell size of it.

Beyond that distance the point is a coordinate error, and the nearest cell would
score a gauge or a piezometer on a place it does not observe. The point gets no
cell and a warning names it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from pyproj import CRS
from shapely.geometry import box

from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.cell_location import locate_cells, locate_cells_near
from hydromodpy.spatial.mesh.request import MeshRequest, RasterGridSpec
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_triangles

WKT = CRS.from_epsg(2154).to_wkt()
SIZE = 10.0


def _grid() -> PlanarCellMesh:
    """Three columns and two rows of 10 m cells on [0, 30] x [0, 20]."""
    request = MeshRequest(
        domain=box(0.0, 0.0, 30.0, 20.0),
        crs_wkt=WKT,
        grid=RasterGridSpec(
            xmin=0.0, xmax=30.0, ymin=0.0, ymax=20.0, dx=SIZE, dy=SIZE, nrow=2, ncol=3, crs_wkt=WKT
        ),
        nominal_size_m=SIZE,
    )
    return RegularMeshEngine().build(request)


def test_a_point_inside_the_mesh_gets_the_cell_that_holds_it() -> None:
    grid = _grid()
    points = np.array([[5.0, 15.0], [25.0, 5.0], [15.0, 10.0]])
    np.testing.assert_array_equal(
        locate_cells_near(grid, points), locate_cells(grid, points, allow_nearest=False)
    )


def test_a_point_within_a_cell_size_takes_the_nearest_cell() -> None:
    # 9 m east of the east side, beside the south-east cell (row 1, column 2).
    assert locate_cells_near(_grid(), np.array([[39.0, 5.0]])).tolist() == [1 * 3 + 2]


def test_a_point_farther_than_a_cell_size_is_lost_and_named(caplog) -> None:
    with caplog.at_level("WARNING"):
        cells = locate_cells_near(_grid(), np.array([[41.0, 5.0], [39.0, 5.0]]))
    assert cells.tolist() == [-1, 1 * 3 + 2]
    assert "(41.00, 5.00)" in caplog.text
    assert "(39.00, 5.00)" not in caplog.text


def test_the_bound_is_the_size_of_the_nearest_cell_on_triangles() -> None:
    cell_mesh = bundle_triangles(BUNDLE_CASES[2])
    xmin, ymin, xmax, ymax = cell_mesh.mesh.bounds()
    probe = np.array([[xmax + 1.0e4, 0.5 * (ymin + ymax)]])
    assert locate_cells_near(cell_mesh, probe).tolist() == [-1]
    centre = cell_mesh.centers[[0]]
    assert locate_cells_near(cell_mesh, centre).tolist() == [0]


def test_the_boussinesq_adapter_locates_no_cell_far_from_its_mesh() -> None:
    cell_mesh = _grid()
    ctx = SimpleNamespace(model=SimpleNamespace(mesh=SimpleNamespace(cell_mesh=cell_mesh)))
    adapter = BoussinesqFlowAdapter()
    assert adapter.locate_cell(ctx, 39.0, 5.0) == (0, 0, 1 * 3 + 2)
    assert adapter.locate_cell(ctx, 41.0, 5.0) is None
