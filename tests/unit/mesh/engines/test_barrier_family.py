"""The barrier family: the triangle and voronoi faces follow a wall exactly, wings included.

The reservoir of ``tests/_helpers/reservoir_dam.py`` is meshed through the real
planner around its cutoff wall laid on the shore; a river crosses a free barrier
in the other cases.
"""

from __future__ import annotations

import functools

import numpy as np
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.physics.flow.cutoff_wall_shore import SnappedWall, snap_wall_to_shore
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.engines.voronoi.constraints import place_constraints
from hydromodpy.spatial.mesh.engines.voronoi.frame import SizeSampler, local_frame
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.flow_barrier import (
    BarrierFace,
    crossed_edges,
    downstream_of_wall,
    wall_leaks,
)
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, MeshRequest, RasterGridSpec
from tests._helpers.reservoir_dam import DOMAIN, X0, Y0, reservoir, trace

WKT = CRS.from_epsg(2154).to_wkt()
EXACT = ("triangle", "voronoi")
ON_LINE_M = 1.0e-3
"""The voronoi gate G2 puts a pair face within 1 mm of its segment ends."""

_GRADED = {
    "cell_size": 60.0,
    "river_cell_size": 20.0,
    "lake_refinement": {"cell_size": 30.0, "dam_cell_size": 15.0, "dam_buffer": 60.0},
}


def _grid() -> RasterGridSpec:
    xmin, ymin, xmax, ymax = DOMAIN.bounds
    return RasterGridSpec(
        xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, dx=10.0, dy=10.0, nrow=80, ncol=120, crs_wkt=WKT
    )


def _request(
    engine: str,
    barriers: tuple[LineString, ...],
    *,
    lakes: tuple = (),
    river: LineString | None = None,
) -> MeshRequest:
    mesh = (
        {"engine": engine, **_GRADED} if engine in EXACT else {"engine": engine, "cell_size": 40.0}
    )
    if river is None and engine in EXACT:
        mesh["families"] = {"rivers": "none"}
    inputs = PlanningInputs(
        dem_grid=_grid(),
        crs_wkt=WKT,
        domain=DOMAIN,
        river_trace=None
        if river is None
        else RiverMeshTrace(source_kind="file", crs_wkt=WKT, lines=(river,)),
        watershed=DOMAIN,
        lakes=lakes,
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=False,
        barriers=barriers,
    )
    return plan_mesh_request(MeshConfig.model_validate(mesh), inputs)


@functools.cache
def _walled(engine: str, offset: float) -> tuple[SnappedWall, MeshRequest, PlanarCellMesh]:
    wall = snap_wall_to_shore(reservoir(), trace(offset), 50.0)
    request = _request(engine, (wall.line,), lakes=(wall.polygon,))
    return wall, request, registry.create(engine).build(request)


def _river_crossing(angle_deg: float) -> tuple[LineString, LineString]:
    centre = np.array([X0 + 600.0, Y0 + 400.0])
    tangent = np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])
    barrier = LineString([centre - 250.0 * tangent, centre + 250.0 * tangent])
    river = LineString(
        [(X0 + 50.0, Y0 + 410.0), (X0 + 600.0, Y0 + 400.0), (X0 + 1150.0, Y0 + 380.0)]
    )
    return barrier, river


def _rows(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """``(cell_a, cell_b, node_a, node_b)`` of the interior rows of one family."""
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family) & (table.cell_b >= 0)
    return np.column_stack(
        [table.cell_a[rows], table.cell_b[rows], table.node_a[rows], table.node_b[rows]]
    )


def _pairs(rows: np.ndarray) -> list[tuple[int, int]]:
    return [tuple(pair) for pair in np.sort(rows[:, :2], axis=1).tolist()]


def _node_gap(cell_mesh: PlanarCellMesh, rows: np.ndarray, line: LineString) -> float:
    """The largest distance [m] from a face node of *rows* to *line*."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    return float(shapely.distance(shapely.points(vertices[rows[:, 2:].ravel()]), line).max())


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", EXACT)
def test_the_wall_faces_lie_on_the_wall_line(engine: str, offset: float) -> None:
    _, request, cell_mesh = _walled(engine, offset)
    line = request.family(BARRIER_FAMILY).lines[0]
    rows = _rows(cell_mesh, BARRIER_FAMILY)
    qa = cell_mesh.qa.families[BARRIER_FAMILY]

    assert _node_gap(cell_mesh, rows, line) < ON_LINE_M
    assert qa["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert qa["mixed_cells"] == 0.0


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", EXACT)
def test_each_shore_face_is_one_face_of_both_families(engine: str, offset: float) -> None:
    wall, _, cell_mesh = _walled(engine, offset)
    barrier = _pairs(_rows(cell_mesh, BARRIER_FAMILY))
    lakes = _pairs(_rows(cell_mesh, "lakes"))
    shared = set(barrier) & set(lakes)
    rows = _rows(cell_mesh, BARRIER_FAMILY)
    on_shore = [
        pair
        for pair, gap in zip(
            barrier, shapely.distance(shapely.points(_midpoints(cell_mesh, rows)), wall.shore)
        )
        if gap < ON_LINE_M
    ]

    assert len(barrier) == len(set(barrier))
    assert len(lakes) == len(set(lakes))
    assert len(shared) >= 5
    assert set(on_shore) <= shared


def _midpoints(cell_mesh: PlanarCellMesh, rows: np.ndarray) -> np.ndarray:
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    return 0.5 * (vertices[rows[:, 2]] + vertices[rows[:, 3]])


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", EXACT)
def test_every_barrier_row_keeps_the_lake_on_its_left(engine: str, offset: float) -> None:
    wall, _, cell_mesh = _walled(engine, offset)
    rows = _rows(cell_mesh, BARRIER_FAMILY)
    lake = shapely.contains_xy(wall.polygon, *cell_mesh.centers.T)

    assert not downstream_of_wall(wall.line, cell_mesh.centers[rows[:, 0]]).any()
    assert downstream_of_wall(wall.line, cell_mesh.centers[rows[:, 1]]).sum() >= len(rows) // 2
    assert not lake[rows[:, 1]].any()


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_the_shared_stretch_is_fed_once_to_the_voronoi_generator(offset: float) -> None:
    _, request, _ = _walled("voronoi", offset)
    field = request.size_field
    lines = resample_families(request.lines, domain=request.domain, size_field=field).families
    frame = local_frame(request.domain)
    plan = place_constraints(
        MeshRequest(
            domain=request.domain,
            crs_wkt=request.crs_wkt,
            grid=request.grid,
            nominal_size_m=request.nominal_size_m,
            lines=lines,
            size_field=field,
        ),
        frame,
        SizeSampler(field, frame),
    )
    faces = plan.faces
    pairs = {tuple(sorted(pair)) for pair in faces.segment_nodes.tolist()}
    barrier = plan.family_names.index(BARRIER_FAMILY)

    assert len(pairs) == len(faces.segment_nodes)
    assert np.count_nonzero(faces.alias_family == barrier) >= 5
    assert np.all(faces.segment_family[faces.alias_segment] == plan.family_names.index("lakes"))
    assert plan.family_stats[BARRIER_FAMILY]["yielded_segments"] == 0.0


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", EXACT)
def test_the_wings_meet_the_shore_at_its_corners_and_reach_their_ends(
    engine: str, offset: float
) -> None:
    wall, request, cell_mesh = _walled(engine, offset)
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    barrier = _rows(cell_mesh, BARRIER_FAMILY)
    lakes = _rows(cell_mesh, "lakes")
    line = request.family(BARRIER_FAMILY).lines[0]

    for corner in (wall.shore.coords[0], wall.shore.coords[-1]):
        node = int(np.argmin(np.hypot(*(vertices - corner).T)))
        assert np.hypot(*(vertices[node] - corner)) < ON_LINE_M
        assert np.count_nonzero(barrier[:, 2:] == node) == 2
        assert np.count_nonzero(lakes[:, 2:] == node) == 2
    for end in (line.coords[0], line.coords[-1]):
        assert np.hypot(*(vertices[barrier[:, 2:].ravel()] - end).T).min() < ON_LINE_M


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", EXACT)
def test_nothing_reaches_the_lake_side_from_downstream_across_the_family(
    engine: str, offset: float
) -> None:
    wall, _, cell_mesh = _walled(engine, offset)
    lake = np.flatnonzero(shapely.contains_xy(wall.polygon, *cell_mesh.centers.T))
    faces = [BarrierFace(a, b, 0.0) for a, b in _pairs(_rows(cell_mesh, BARRIER_FAMILY))]

    assert wall_leaks(cell_mesh, wall.line, lake, faces, reach=100.0).size == 0
    assert wall_leaks(cell_mesh, wall.line, lake, faces[::2], reach=100.0).size > 0


@pytest.mark.parametrize("angle", [90.0, 30.0, 15.0])
@pytest.mark.parametrize("engine", EXACT)
def test_a_river_crosses_the_barrier_once_between_two_chain_cells(
    engine: str, angle: float
) -> None:
    barrier, river = _river_crossing(angle)
    request = _request(engine, (barrier,), river=river)
    cell_mesh = registry.create(engine).build(request)
    (chain,) = cell_mesh.chains("rivers")
    links = {
        tuple(sorted(link))
        for link in zip(chain.cell_ids[:-1].tolist(), chain.cell_ids[1:].tolist(), strict=True)
        if link[0] != link[1]
    }
    faces = set(_pairs(_rows(cell_mesh, BARRIER_FAMILY)))
    qa = cell_mesh.qa.families

    assert len(links & faces) == 1
    assert qa["rivers"]["breaks"] == 0.0
    assert qa[BARRIER_FAMILY]["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert _node_gap(cell_mesh, _rows(cell_mesh, BARRIER_FAMILY), barrier) < ON_LINE_M
    if engine == "voronoi":
        assert qa[BARRIER_FAMILY]["yielded_segments"] == 0.0
        assert qa[BARRIER_FAMILY]["merged_circles"] == 0.0


def test_the_regular_staircase_is_the_faces_the_barrier_crosses() -> None:
    barrier = LineString([(X0 + 210.0, Y0 + 110.0), (X0 + 830.0, Y0 + 590.0)])
    cell_mesh = registry.create("regular").build(_request("regular", (barrier,)))
    geometry = cell_mesh.geometry
    stairs = {
        tuple(pair)
        for pair in geometry.edge_cells[
            crossed_edges(geometry, cell_mesh.centers, barrier)
        ].tolist()
    }

    assert set(_pairs(_rows(cell_mesh, BARRIER_FAMILY))) == stairs
    assert len(stairs) > 10


def test_a_family_switched_off_leaves_no_barrier_face() -> None:
    barrier = LineString([(X0 + 210.0, Y0 + 110.0), (X0 + 830.0, Y0 + 590.0)])
    inputs = PlanningInputs(
        dem_grid=_grid(),
        crs_wkt=WKT,
        domain=box(*DOMAIN.bounds),
        river_trace=None,
        watershed=DOMAIN,
        lakes=(),
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=False,
        barriers=(barrier,),
    )
    config = MeshConfig.model_validate(
        {
            "engine": "triangle",
            "cell_size": 60.0,
            "families": {"rivers": "none", "barriers": "none"},
        }
    )
    cell_mesh = registry.create("triangle").build(plan_mesh_request(config, inputs))

    assert not cell_mesh.face_rows(BARRIER_FAMILY).any()
