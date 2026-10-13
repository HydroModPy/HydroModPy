from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.adapters.cell_mesh import cell_mesh_from_triangulation
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.gmsh_grid import GmshSupportMetadata
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec
from tests._helpers.cell_meshes import TEST_CRS_WKT

_GRID_CRS_WKT = CRS.from_epsg(2154).to_wkt()


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def regular_solver_mesh(
    nrow: int, ncol: int, *, top: float = 10.0, river: LineString | None = None
) -> SolverMesh:
    """Return the solver mesh of the ``regular`` engine on ``nrow`` x ``ncol`` unit cells.

    The engine gives the cell mesh its ``boundary:<side>`` families, which
    ``solver_mesh_from_structured_arrays`` does not. ``river`` is a line the engine
    rasterizes into a chain of river cells.
    """
    request = MeshRequest(
        domain=box(0.0, 0.0, float(ncol), float(nrow)),
        crs_wkt=_GRID_CRS_WKT,
        grid=RasterGridSpec(
            xmin=0.0,
            xmax=float(ncol),
            ymin=0.0,
            ymax=float(nrow),
            dx=1.0,
            dy=1.0,
            nrow=nrow,
            ncol=ncol,
            crs_wkt=_GRID_CRS_WKT,
        ),
        nominal_size_m=1.0,
        lines=() if river is None else (LineFamilySpec("rivers", "cell", (river,)),),
    )
    cell_mesh = RegularMeshEngine().build(request)
    n_cells = nrow * ncol
    return SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, top),
        botm=np.full((1, n_cells), top - 9.0),
        inactive_mask=np.zeros((1, n_cells), dtype=bool),
    )


def _build_model() -> Modflow6:
    dem = np.array([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = Modflow6(geographic=geo, model_folder=".")
    model.solver_mesh = regular_solver_mesh(2, 3)
    model.nlay = 1
    model.ncpl = 6
    model.nper = 2
    model.steady = np.array([False, False])  # all transient by default
    model.dem_mask = np.zeros(6, dtype=bool)  # flat (ncpl,)
    model.time_grid = SimpleNamespace(
        window=ResolvedSimulationTimeWindow(
            start=pd.Timestamp("2003-01-01"),
            end=pd.Timestamp("2003-02-28"),
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        )
    )
    return model


def _build_unstructured_runtime(
    *,
    river_internal_edge: bool = False,
    boundary_labels_by_edge_id: dict[int, str] | None = None,
) -> tuple[SolverMesh, GmshSupportMetadata]:
    vertices = np.asarray(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ],
        dtype=float,
    )
    connectivity = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=int)
    planar_mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )
    support = GmshSupportMetadata(
        cell_ids=np.asarray([0, 1], dtype=int),
        node_ids=np.asarray([0, 1, 2, 3], dtype=int),
        node_x_m=vertices[:, 0],
        node_y_m=vertices[:, 1],
        cell_node_indices=((0, 1, 2), (0, 2, 3)),
        cell_centroid_x_m=np.asarray([2.0 / 3.0, 1.0 / 3.0], dtype=float),
        cell_centroid_y_m=np.asarray([1.0 / 3.0, 2.0 / 3.0], dtype=float),
        edge_ids=np.asarray([0, 1, 2, 3, 4], dtype=int),
        edge_node_a_index=np.asarray([0, 1, 2, 3, 0], dtype=int),
        edge_node_b_index=np.asarray([1, 2, 3, 0, 2], dtype=int),
        edge_cell_a=np.asarray([0, 0, 1, 1, 0], dtype=int),
        edge_cell_b=np.asarray([-1, -1, -1, -1, 1], dtype=int),
        edge_midpoint_x_m=np.asarray([0.5, 1.0, 0.5, 0.0, 0.5], dtype=float),
        edge_midpoint_y_m=np.asarray([0.0, 0.5, 1.0, 0.5, 0.5], dtype=float),
        edge_kind=("boundary", "boundary", "boundary", "boundary", "internal"),
        edge_is_river=np.asarray(
            [False, False, False, False, bool(river_internal_edge)], dtype=bool
        ),
        geology_a_key=("", "", "", "", ""),
        geology_b_key=("", "", "", "", ""),
        boundary_labels_by_edge_id={
            0: "south_side",
            1: "east_side",
            2: "north_side",
            3: "west_side",
            **(boundary_labels_by_edge_id or {}),
        },
    )
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh_from_triangulation(planar_mesh, support, crs_wkt=TEST_CRS_WKT),
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )
    return solver_mesh, support


def _build_unstructured_model(
    *,
    river_internal_edge: bool = False,
    boundary_labels_by_edge_id: dict[int, str] | None = None,
) -> Modflow6:
    model = _build_model()
    solver_mesh, _ = _build_unstructured_runtime(
        river_internal_edge=river_internal_edge,
        boundary_labels_by_edge_id=boundary_labels_by_edge_id,
    )
    model.solver_mesh = solver_mesh
    model.nlay = 1
    model.ncpl = 2
    model.dem_mask = np.zeros(2, dtype=bool)
    return model
