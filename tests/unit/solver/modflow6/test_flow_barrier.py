"""Horizontal flow barrier (HFB) rows of MODFLOW 6 built from a barrier line.

A barrier line carved to a depth (m) or between a base and a crest elevation (m) bars the
faces between cells that it crosses or that the mesh lays on it. A row is a pair of cells
(layer, cell) with a hydraulic characteristic (1/day or 1/s as the model holds it). The
last tests run the real mesh planner on a 1200 m by 800 m box.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import LineString

from hydromodpy.mesh import registry
from hydromodpy.mesh.cells.barrier_faces import barrier_edges, crossed_edges
from hydromodpy.mesh.engines.triangle.gmsh_triangulation import MESH_SIZE_PER_CELL_SIZE
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import FaceFamilyTable, PlanarCellMesh
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import BARRIER_FAMILY
from hydromodpy.model.boundaries.barriers import apply_flow_barriers_to_flow
from hydromodpy.model.boundaries.lakes import apply_cutoff_wall_to_flow
from hydromodpy.model.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.solver.modflow6.builders._lake_geometry import downstream_of_wall
from hydromodpy.solver.modflow6.builders.flow_barrier import (
    build_flow_barrier_hfb,
    resolve_flow_barrier_hfb_rows,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_over, planning_inputs
from tests._helpers.model_factory import make_model
from tests._helpers.reservoir_dam import DOMAIN, X0, Y0
from tests._helpers.solver_meshes import solver_mesh_from

# A near-vertical trace across a 2x2 grid of unit quads (c0=(0,0), c1=(1,0), c2=(0,1),
# c3=(1,1)). It separates the left column from the right one at both rows, so it bars the
# connected faces (0, 1) and (2, 3).
CUT_COORDS = [[1.01, -0.5], [1.01, 2.5]]
CUT = LineString(CUT_COORDS)


def grid(n: int, botm0: np.ndarray | None = None) -> SolverMesh:
    # n x n unit quads, top = 10 m, layer 0 bottom = botm0 (default 5 m), layer 1 bottom = 0 m.
    verts = np.array([[i, j] for j in range(n + 1) for i in range(n + 1)], dtype=float)

    def v(i: int, j: int) -> int:
        return j * (n + 1) + i

    conn = np.array(
        [[v(i, j), v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)] for j in range(n) for i in range(n)],
        dtype=int,
    )
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    nc = n * n
    b0 = np.full(nc, 5.0) if botm0 is None else botm0
    return solver_mesh_from(
        mesh,
        top=np.full(nc, 10.0),
        botm=np.array([b0, np.zeros(nc)]),
        inactive_mask=np.zeros((2, nc), dtype=bool),
    )


# Layer 0 spans 5-10 m and layer 1 spans 0-5 m, except where botm0 says otherwise.
THICK_TOP_ON_RIGHT = np.array([5.0, 3.0, 5.0, 3.0])  # layer 0 bottom (m), cells c0..c3

BARRED_BANDS = [
    # Crest 4 m and depth 3 m bar [1, 4] m, which skips the top layer.
    pytest.param(None, {"depths": [3.0], "crest_elevation": 4.0}, [1], 2, id="crest below the top"),
    # Floor at 1 m and crest at the cell top (10 m) bar both layers.
    pytest.param(None, {"base_elevation": 1.0}, [0, 1], 4, id="floor to the top"),
    pytest.param(None, {"base_elevation": 2.0}, [0, 1], 4, id="band cutting two layers"),
    # The band [3.5, 4.5] m cuts layer 0 on c1 and layer 1 on c0.
    pytest.param(
        THICK_TOP_ON_RIGHT,
        {"crest_elevation": 4.5, "depths": [1.0]},
        [0, 1],
        4,
        id="layers differ between cells",
    ),
]


@pytest.mark.parametrize(("botm0", "kwargs", "layers", "n_rows"), BARRED_BANDS)
def test_barred_layers(botm0, kwargs, layers, n_rows) -> None:
    rows = build_flow_barrier_hfb(grid(2, botm0), line=CUT, hydchr=1e-9, **kwargs)

    assert sorted({r[0][0] for r in rows}) == layers
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (2, 3)]
    assert len(rows) == n_rows


def test_depth_interpolated_along_line() -> None:
    # Shallow (4 m) at the start (bottom), deep (7 m) at the end (top) of the trace.
    rows = build_flow_barrier_hfb(grid(2), line=CUT, depths=[4.0, 7.0], hydchr=1e-9)
    by_face: dict[tuple[int, int], list[int]] = {}
    for r in rows:
        by_face.setdefault((r[0][1], r[1][1]), []).append(r[0][0])
    # The shallow end stays in the top layer, the deeper end reaches the bottom layer.
    assert by_face[(0, 1)] == [0]
    assert sorted(by_face[(2, 3)]) == [0, 1]


def test_hydchr_weighted_by_trace_length() -> None:
    # A diagonal trace bars a staircase of faces longer than the trace itself.
    sm = grid(6)
    line = LineString([(0.0, 0.3), (6.0, 5.7)])
    qa: dict = {}
    rows = build_flow_barrier_hfb(sm, line=line, hydchr=1e-6, depths=[2.0], qa=qa)
    edge_len = {}
    geo = sm.cell_mesh.geometry
    for e in np.flatnonzero(geo.edge_cells[:, 1] >= 0):
        a, b = sorted(int(c) for c in geo.edge_cells[e])
        edge_len[(a, b)] = float(geo.edge_length[e])
    total = sum(r[2] * edge_len[tuple(sorted((r[0][1], r[1][1])))] for r in rows)
    trace = line.length
    assert total == pytest.approx(1e-6 * trace, rel=1e-9)
    assert all(r[2] < 1e-6 for r in rows)
    assert qa["chain_over_trace"] > 1.0


def test_open_end_warns_with_gap(caplog) -> None:
    sm = grid(4)
    line = LineString([(2.01, -0.5), (2.01, 2.5)])  # stops 1.5 m short of the top edge
    qa: dict = {}
    with caplog.at_level(logging.WARNING):
        build_flow_barrier_hfb(sm, line=line, hydchr=1e-9, depths=[2.0], qa=qa)
    assert qa["open_length_start"] == pytest.approx(0.0, abs=1e-9)
    assert qa["open_length_end"] == pytest.approx(1.5, abs=1e-9)
    assert any("open" in rec.message for rec in caplog.records if rec.levelno >= logging.WARNING)
    assert qa["faces_per_layer"] == {0: 2}


def resolver_model(sinks_sources: dict, *, xt3d: bool | None = None) -> SimpleNamespace:
    model = SimpleNamespace(inputs=make_model(**sinks_sources))
    if xt3d is not None:
        model.modflow_config = SimpleNamespace(runtime=SimpleNamespace(mf6_enable_xt3d=xt3d))
    return model


def test_zero_hydchr_refused_under_xt3d() -> None:
    cfg = FlowBarrierConfig(line=CUT_COORDS, depths=[7.0], hydchr=0.0)
    sinks_sources = {"flow_barriers": {"w": {"barrier": cfg, "line": CUT}}}

    with pytest.raises(ValueError, match="XT3D"):
        resolve_flow_barrier_hfb_rows(resolver_model(sinks_sources, xt3d=True), grid(2))
    rows = resolve_flow_barrier_hfb_rows(resolver_model(sinks_sources, xt3d=False), grid(2))
    assert rows and all(r[2] == 0.0 for r in rows)


def test_bound_cutoff_wall_gives_rows() -> None:
    wall = FlowBarrierConfig(line=CUT_COORDS, depths=[7.0], hydchr=1e-9)
    payload = {"cutoff_wall": wall, "cutoff_wall_line": CUT}

    rows = resolve_flow_barrier_hfb_rows(resolver_model({"lakes": {"reservoir": payload}}), grid(2))

    assert len(rows) == 4  # depth 7 m spans both 5 m layers across the two faces
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert all(r[2] == pytest.approx(1e-9) for r in rows)


def test_no_barrier_no_rows() -> None:
    model = resolver_model({"lakes": {"reservoir": {"bedleak": 1e-6}}})
    assert resolve_flow_barrier_hfb_rows(model, grid(2)) == []


def test_lake_wall_and_general_barrier() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "initial_stage": "8 m",
            "cutoff_wall": {"line": CUT_COORDS, "depths": [4.0], "hydchr": 1e-9},
        }
    )
    barrier = FlowBarrierConfig(line=CUT_COORDS, depths=[7.0], hydchr=1e-9)
    flow = SimpleNamespace(
        sinks_sources={"lakes": {"reservoir": lake}, "flow_barriers": {"wall_a": barrier}}
    )
    apply_cutoff_wall_to_flow(flow=flow)
    apply_flow_barriers_to_flow(flow=flow)
    rows = resolve_flow_barrier_hfb_rows(resolver_model(flow.sinks_sources), grid(2))
    # lake wall (depth 4 -> layer 0, 2 faces) + general barrier (depth 7 -> 2 layers, 4 rows)
    assert len(rows) == 2 + 4


FENCE = LineString([(X0 + 250.0, Y0 + 120.0), (X0 + 560.0, Y0 + 420.0), (X0 + 880.0, Y0 + 500.0)])
# The cell size whose triangles have 40 m edges, so an 80 m gap holds at least two faces.
TRIANGLE_CELL_SIZE = 40.0 / MESH_SIZE_PER_CELL_SIZE["delaunay"]
MESHES = {
    "regular": {"engine": "regular", "cell_size": 40.0},
    "triangle": {
        "engine": "triangle",
        "cell_size": TRIANGLE_CELL_SIZE,
        "families": {"rivers": "none"},
    },
    "voronoi": {"engine": "voronoi", "cell_size": 40.0, "families": {"rivers": "none"}},
}


@functools.cache
def _mesh(engine: str) -> PlanarCellMesh:
    inputs = planning_inputs(
        grid_over(DOMAIN, 10.0, crs_wkt=LAMBERT93_WKT),
        domain=DOMAIN,
        watershed=DOMAIN,
        synthetic=False,
        barriers=(FENCE,),
    )
    request = plan_mesh_request(MeshConfig.model_validate(MESHES[engine]), inputs)
    return registry.mesh_engines.create(engine).build(request)


def _planned_hfb(cell_mesh: PlanarCellMesh) -> list[list]:
    n_cells = cell_mesh.n_cells
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, 10.0),
        botm=np.stack([np.full(n_cells, 5.0), np.zeros(n_cells)]),
        idomain=np.ones((2, n_cells), dtype=int),
    )
    barrier = FlowBarrierConfig(line=[list(xy) for xy in FENCE.coords], depths=[8.0], hydchr=1e-9)
    model = SimpleNamespace(
        inputs=make_model(flow_barriers={"f": {"barrier": barrier, "line": FENCE}})
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


def test_regular_grid_bars_crossed_staircase() -> None:
    cell_mesh = _mesh("regular")
    geometry = cell_mesh.geometry
    crossed = crossed_edges(geometry, cell_mesh.centers, FENCE)
    barred = _barred(_planned_hfb(cell_mesh))

    assert barred == {tuple(pair) for pair in geometry.edge_cells[crossed].tolist()}
    assert _leaks(cell_mesh, barred) == 0


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_crossed_faces_close_family_gap(engine: str) -> None:
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


WALL = FlowBarrierConfig(line=CUT_COORDS, depths=[7.0], hydchr=1e-9)
OFF_MESH = LineString([(10.0, 10.0), (11.0, 11.0)])

REFUSALS = [
    pytest.param({"barrier": WALL}, "not resolved", id="barrier without its line"),
    pytest.param(
        {"barrier": WALL, "line": OFF_MESH}, "crosses no interior mesh face", id="line off the mesh"
    ),
]


@pytest.mark.parametrize(("barrier", "match"), REFUSALS)
def test_refusals(barrier: dict, match: str) -> None:
    # A declared wall must fail loudly, not build a model without it.
    model = resolver_model({"flow_barriers": {"wall_a": barrier}})
    with pytest.raises(ValueError, match=match):
        resolve_flow_barrier_hfb_rows(model, grid(2))
