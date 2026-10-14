from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import FaceFamilyTable
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec
from tests._helpers.cell_meshes import TEST_CRS_WKT, cell_mesh_of

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
) -> SolverMesh:
    """Return two triangles on the unit square, with their river and boundary face families.

    Edges 0 to 3 are the south, east, north and west sides; edge 4 is the diagonal.
    ``boundary_labels_by_edge_id`` renames the family of a side edge.
    """
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
    edge_nodes = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 2)]
    edge_cells = [(0, -1), (0, -1), (1, -1), (1, -1), (0, 1)]
    labels = {0: "south_side", 1: "east_side", 2: "north_side", 3: "west_side"}
    labels.update(boundary_labels_by_edge_id or {})
    selections = {"rivers": [4]} if river_internal_edge else {}
    for label in sorted(set(labels.values())):
        rows = [edge for edge, edge_label in labels.items() if edge_label == label]
        selections[f"boundary:{label.removesuffix('_side')}"] = sorted(rows)
    rows = [edge for edges in selections.values() for edge in edges]
    faces = FaceFamilyTable(
        names=tuple(selections),
        family=np.repeat(np.arange(len(selections)), [len(edges) for edges in selections.values()]),
        cell_a=[edge_cells[edge][0] for edge in rows],
        cell_b=[edge_cells[edge][1] for edge in rows],
        node_a=[edge_nodes[edge][0] for edge in rows],
        node_b=[edge_nodes[edge][1] for edge in rows],
        zone_left=np.full(len(rows), -1),
        zone_right=np.full(len(rows), -1),
    )
    return SolverMesh(
        cell_mesh=replace(cell_mesh_of(planar_mesh), face_families=faces),
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


def _build_unstructured_model(
    *,
    river_internal_edge: bool = False,
    boundary_labels_by_edge_id: dict[int, str] | None = None,
) -> Modflow6:
    model = _build_model()
    model.solver_mesh = _build_unstructured_runtime(
        river_internal_edge=river_internal_edge,
        boundary_labels_by_edge_id=boundary_labels_by_edge_id,
    )
    model.nlay = 1
    model.ncpl = 2
    model.dem_mask = np.zeros(2, dtype=bool)
    return model
