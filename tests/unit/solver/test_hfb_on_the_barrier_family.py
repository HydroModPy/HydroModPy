"""A flow barrier bars the faces the mesh lays on it, and the faces it crosses only in a gap.

The meshes come from the real planner on a 1200 m by 800 m box, the barrier in
the barrier family as the mesh step puts it there.
"""

from __future__ import annotations

import dataclasses
import functools
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from pyproj import CRS
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import LineString

from hydromodpy.physics.flow.sinks_sources import FlowBarrierConfig
from hydromodpy.solver.modflow6.builders import resolve_flow_barrier_hfb_rows
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.model.planar_cell_mesh import FaceFamilyTable, PlanarCellMesh
from hydromodpy.spatial.mesh.ops.flow_barrier import (
    barrier_edges,
    crossed_edges,
    downstream_of_wall,
)
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, RasterGridSpec
from tests._helpers.reservoir_dam import DOMAIN, X0, Y0

WKT = CRS.from_epsg(2154).to_wkt()
FENCE = LineString([(X0 + 250.0, Y0 + 120.0), (X0 + 560.0, Y0 + 420.0), (X0 + 880.0, Y0 + 500.0)])
MESHES = {
    "regular": {"engine": "regular", "cell_size": 40.0},
    "triangle": {"engine": "triangle", "cell_size": 40.0, "families": {"rivers": "none"}},
    "voronoi": {"engine": "voronoi", "cell_size": 40.0, "families": {"rivers": "none"}},
}


@functools.cache
def _mesh(engine: str) -> PlanarCellMesh:
    xmin, ymin, xmax, ymax = DOMAIN.bounds
    grid = RasterGridSpec(
        xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, dx=10.0, dy=10.0, nrow=80, ncol=120, crs_wkt=WKT
    )
    inputs = PlanningInputs(
        dem_grid=grid,
        crs_wkt=WKT,
        domain=DOMAIN,
        river_trace=None,
        watershed=DOMAIN,
        lakes=(),
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=False,
        barriers=(FENCE,),
    )
    request = plan_mesh_request(MeshConfig.model_validate(MESHES[engine]), inputs)
    return registry.create(engine).build(request)


def _hfb(cell_mesh: PlanarCellMesh) -> list[list]:
    n_cells = cell_mesh.n_cells
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, 10.0),
        botm=np.stack([np.full(n_cells, 5.0), np.zeros(n_cells)]),
        inactive_mask=np.zeros((2, n_cells), dtype=bool),
    )
    barrier = FlowBarrierConfig(line=[list(xy) for xy in FENCE.coords], depths=[8.0], hydchr=1e-9)
    model = SimpleNamespace(
        flow=SimpleNamespace(
            sinks_sources={"flow_barriers": {"f": {"barrier": barrier, "line": FENCE}}}
        )
    )
    return resolve_flow_barrier_hfb_rows(model, solver_mesh)


def _family_pairs(cell_mesh: PlanarCellMesh) -> set[tuple[int, int]]:
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(BARRIER_FAMILY) & (table.cell_b >= 0)
    return {
        tuple(sorted(pair)) for pair in zip(table.cell_a[rows], table.cell_b[rows], strict=True)
    }


def _leaks(cell_mesh: PlanarCellMesh, barred: set[tuple[int, int]]) -> int:
    """Cells on one side of the fence reached from the other within 100 m of it."""
    centres = cell_mesh.centers
    along = shapely.line_locate_point(FENCE, shapely.points(centres))
    near = (shapely.distance(shapely.points(centres), FENCE) < 100.0) & (along > 1.0)
    near &= along < FENCE.length - 1.0
    right = downstream_of_wall(FENCE, centres) & near
    left = downstream_of_wall(LineString(FENCE.coords[::-1]), centres) & near
    pairs = cell_mesh.geometry.edge_cells[cell_mesh.geometry.edge_cells[:, 1] >= 0]
    keep = np.array([tuple(pair) not in barred for pair in pairs.tolist()])
    keep &= near[pairs[:, 0]] & near[pairs[:, 1]]
    graph = coo_matrix(
        (np.ones(keep.sum()), (pairs[keep, 0], pairs[keep, 1])), shape=(cell_mesh.n_cells,) * 2
    )
    component = connected_components(graph, directed=False)[1]
    return int(np.isin(component[left], component[right]).sum())


def _barred(rows: list[list]) -> set[tuple[int, int]]:
    return {tuple(sorted((row[0][1], row[1][1]))) for row in rows}


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_a_flow_barrier_bars_the_faces_the_mesh_lays_on_it(engine: str) -> None:
    cell_mesh = _mesh(engine)
    barred = _barred(_hfb(cell_mesh))
    geometry = cell_mesh.geometry
    edge_of = {tuple(pair): k for k, pair in enumerate(geometry.edge_cells.tolist())}
    middle = geometry.edge_midpoint[[edge_of[pair] for pair in sorted(barred)]]

    assert barred == _family_pairs(cell_mesh)
    assert shapely.distance(shapely.points(middle), FENCE).max() < 1.0e-3
    assert _leaks(cell_mesh, barred) == 0


def test_the_regular_grid_bars_the_staircase_the_barrier_crosses() -> None:
    cell_mesh = _mesh("regular")
    geometry = cell_mesh.geometry
    crossed = crossed_edges(geometry, cell_mesh.centers, FENCE)
    barred = _barred(_hfb(cell_mesh))

    assert barred == {tuple(pair) for pair in geometry.edge_cells[crossed].tolist()}
    assert _leaks(cell_mesh, barred) == 0


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_the_faces_the_barrier_crosses_close_a_gap_in_the_family(engine: str) -> None:
    cell_mesh = _mesh(engine)
    table = cell_mesh.face_families
    rows = np.flatnonzero(cell_mesh.face_rows(BARRIER_FAMILY))
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    middle = 0.5 * (vertices[table.node_a[rows]] + vertices[table.node_b[rows]])
    along = shapely.line_locate_point(FENCE, shapely.points(middle))
    gap = rows[np.abs(along - 0.5 * FENCE.length) < 40.0]
    keep = np.setdiff1d(np.arange(table.n_rows), gap)
    holed = dataclasses.replace(
        cell_mesh,
        face_families=FaceFamilyTable(
            names=table.names,
            **{
                column: getattr(table, column)[keep]
                for column in ("family", "cell_a", "cell_b", "node_a", "node_b")
            },
            zone_left=table.zone_left[keep],
            zone_right=table.zone_right[keep],
        ),
    )
    edges = barrier_edges(holed, FENCE)
    pairs = {tuple(pair) for pair in holed.geometry.edge_cells[edges].tolist()}

    assert gap.size >= 2
    assert _leaks(holed, _family_pairs(holed)) > 0
    assert _leaks(holed, pairs) == 0
    assert _family_pairs(holed) < pairs
