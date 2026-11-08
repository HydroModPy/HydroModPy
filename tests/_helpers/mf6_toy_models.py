"""Small MODFLOW 6 models for the unit tests of the boundary-condition builders.

``toy_model`` is a ``Modflow6`` on a 2 x 3 regular grid of unit cells, two
transient monthly periods, whose ``inputs`` is a ``Model`` of the factory with the
members the test gives. ``two_triangle_model`` swaps its grid for the two
triangles of ``two_triangle_solver_mesh``. ``regular_solver_mesh`` is the solver
mesh the ``regular`` engine builds on unit cells. Not public API.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
from shapely.geometry import LineString

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import FaceFamilyTable
from hydromodpy.mesh.request import LineFamilySpec
from hydromodpy.model.domain.geometry import CatchmentGeometry, RasterGeometry
from hydromodpy.model.model import Geometry, ModelTime
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.channel_tree import channel_rasters_for_run
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request
from tests._helpers.model_factory import make_model, small_geometry


class _DummyGeographic:
    """The few geographic members the model reads, for a DEM of unit cells."""

    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def geometry_of(geographic: object | None = None, *, domain: object | None = None) -> Geometry:
    """The ``Geometry`` ``prepare_solver`` builds from a delineation: DEM grid, rasters of A and catchment.

    Without a delineation the DEM grid and the catchment are ``None``, as for a run
    that has none.
    """
    if geographic is None:
        return Geometry(cells=small_geometry().cells, domain=domain)
    return Geometry(
        cells=small_geometry().cells,
        domain=domain,
        raster=RasterGeometry.from_geographic(
            geographic, channel=channel_rasters_for_run(geographic)
        ),
        catchment=CatchmentGeometry.from_geographic(geographic, crs=None),
    )


def regular_solver_mesh(
    nrow: int, ncol: int, *, top: float = 10.0, river: LineString | None = None
) -> SolverMesh:
    """Return the solver mesh of the ``regular`` engine on ``nrow`` x ``ncol`` unit cells.

    The engine gives the cell mesh its ``boundary:<side>`` families, which
    ``solver_mesh_from_structured_arrays`` does not. ``river`` is a line the engine
    rasterizes into a chain of river cells.
    """
    request = mesh_request(
        grid_spec(nrow, ncol, crs_wkt=LAMBERT93_WKT),
        lines=() if river is None else (LineFamilySpec("rivers", "cell", (river,)),),
    )
    cell_mesh = RegularMeshEngine().build(request)
    n_cells = nrow * ncol
    return SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, top),
        botm=np.full((1, n_cells), top - 9.0),
        idomain=np.ones((1, n_cells), dtype=int),
    )


def toy_model(**members) -> Modflow6:
    """Return a ``Modflow6`` on the 2 x 3 regular grid, one layer, two transient monthly periods.

    ``inputs`` is ``make_model(**members)`` with a transient time of the two monthly
    periods and the DEM raster of unit cells.
    """
    dem = np.array([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]], dtype=float)
    model = Modflow6(model_folder=".")
    model.solver_mesh = regular_solver_mesh(2, 3)
    model.nlay = 1
    model.ncpl = 6
    model.nper = 2
    model.perlen = np.array([31.0, 28.0]) * 86400.0
    model.steady = np.array([False, False])  # all transient by default
    model.dem_mask = np.zeros(6, dtype=bool)  # flat (ncpl,)
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-02-28"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )
    members.setdefault(
        "time",
        ModelTime(
            grid=SimpleNamespace(window=window), regime="transient", first_period_steady=True
        ),
    )
    members.setdefault(
        "geometry",
        Geometry(
            cells=small_geometry().cells,
            domain=None,
            raster=RasterGeometry.from_geographic(_DummyGeographic(dem)),
        ),
    )
    model.inputs = make_model(**members)
    return model


def two_triangle_solver_mesh(
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
        idomain=np.ones((1, 2), dtype=int),
    )


def two_triangle_model(
    *,
    river_internal_edge: bool = False,
    boundary_labels_by_edge_id: dict[int, str] | None = None,
    **members,
) -> Modflow6:
    """Return ``toy_model`` on the two triangles of ``two_triangle_solver_mesh``."""
    model = toy_model(**members)
    model.solver_mesh = two_triangle_solver_mesh(
        river_internal_edge=river_internal_edge,
        boundary_labels_by_edge_id=boundary_labels_by_edge_id,
    )
    model.nlay = 1
    model.ncpl = 2
    model.dem_mask = np.zeros(2, dtype=bool)
    return model
