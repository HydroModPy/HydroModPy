"""The reservoir of ``tests/_helpers/reservoir_dam.py`` planned for the voronoi engine.

The planner grades the mesh to 15 m on the dam. A cutoff wall snapped to the
shore at a given offset gives the barrier family, and a river trace gives the rivers.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.catchment.algorithms.river_mesh_trace import RiverMeshTrace
from hydromodpy.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import MeshRequest
from hydromodpy.model.boundaries.cutoff_wall_shore import SnappedWall, snap_wall_to_shore
from tests._helpers import reservoir_dam
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_over, planning_inputs

GRADED = {
    "engine": "voronoi",
    "cell_size": 60.0,
    "river_cell_size": 20.0,
    "lake_refinement": {"cell_size": 30.0, "dam_cell_size": 15.0, "dam_buffer": 60.0},
}
"""The graded voronoi mesh of the reservoir, cells of 15 m on the dam."""

SNAP_TOLERANCE_M = 50.0
"""How far from the shore the wall trace is snapped onto it."""


def _planned(
    walls: tuple[LineString, ...],
    *,
    lakes: tuple[Polygon, ...] = (),
    river: LineString | None = None,
) -> MeshRequest:
    config = dict(GRADED)
    if river is None:
        config["families"] = {"rivers": "none"}
    trace = (
        None
        if river is None
        else RiverMeshTrace(source_kind="file", crs_wkt=LAMBERT93_WKT, lines=(river,))
    )
    inputs = planning_inputs(
        grid_over(reservoir_dam.DOMAIN, 10.0, crs_wkt=LAMBERT93_WKT),
        watershed=reservoir_dam.DOMAIN,
        synthetic=False,
        river_trace=trace,
        lakes=lakes,
        barriers=walls,
    )
    return plan_mesh_request(MeshConfig.model_validate(config), inputs)


@functools.cache
def _walled(offset: float) -> tuple[SnappedWall, MeshRequest]:
    wall = snap_wall_to_shore(
        reservoir_dam.reservoir(), reservoir_dam.trace(offset), SNAP_TOLERANCE_M
    )
    return wall, _planned((wall.line,), lakes=(wall.polygon,))


@functools.cache
def _walled_mesh(offset: float) -> tuple[SnappedWall, MeshRequest, PlanarCellMesh]:
    wall, request = _walled(offset)
    return wall, request, VoronoiMeshEngine().build(request)


@pytest.fixture
def reservoir_request() -> Callable[..., MeshRequest]:
    """Build the planner request of the reservoir domain with walls, lakes and a river."""
    return _planned


@pytest.fixture
def walled_reservoir() -> Callable[[float], tuple[SnappedWall, MeshRequest]]:
    """Return the wall snapped to the dam shore at an offset and the request it gives."""
    return _walled


@pytest.fixture
def walled_reservoir_mesh() -> Callable[[float], tuple[SnappedWall, MeshRequest, PlanarCellMesh]]:
    """Return the wall, the request and the voronoi mesh of the reservoir at an offset."""
    return _walled_mesh
