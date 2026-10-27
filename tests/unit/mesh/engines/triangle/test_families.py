"""Line families of a triangulation: oriented face rows, chains, zones and the groups of a read .msh.

The barrier family is checked around the cutoff wall of
``tests/_helpers/reservoir_dam.py``, laid on the shore of the reservoir and
meshed through the real planner. A river crosses a free barrier in the other
cases.
"""

from __future__ import annotations

import dataclasses
import functools
from importlib.util import find_spec

import numpy as np
import pytest
import shapely
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from scipy.spatial import Delaunay
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.physics.flow.cutoff_wall_shore import SnappedWall, snap_wall_to_shore
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.engines.triangle.engine import (
    TriangleMeshEngine,
    triangulate_request,
)
from hydromodpy.spatial.mesh.engines.triangle.families import edge_lookup
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.flow_barrier import BarrierFace, downstream_of_wall, wall_leaks
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.request import (
    BARRIER_FAMILY,
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
)
from tests._helpers import reservoir_dam as dam
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    LAMBERT93_WKT,
    grid_over,
    mesh_request,
    planning_inputs,
    square_domain,
)

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

X0, Y0 = L93_ORIGIN
SQUARE = square_domain(1000.0, x0=X0, y0=Y0)
RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])


def _square(*lines: LineFamilySpec) -> MeshRequest:
    """The 1 km square at 50 m, by default with a river crossing a contact."""
    if not lines:
        lines = (
            LineFamilySpec("rivers", "cell", (RIVER,)),
            LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
        )
    return mesh_request(grid_over(SQUARE, 100.0), nominal_size_m=50.0, lines=lines)


def _three_zones() -> MeshRequest:
    """Zones a (north-west), b (north-east) and c (south), parted by three contacts."""
    contacts = (
        LineString([(X0 + 500, Y0 + 500), (X0 + 500, Y0 + 1000)]),
        LineString([(X0, Y0 + 500), (X0 + 500, Y0 + 500)]),
        LineString([(X0 + 500, Y0 + 500), (X0 + 1000, Y0 + 500)]),
    )
    return _square(
        LineFamilySpec("rivers", "cell", (RIVER,)),
        LineFamilySpec("geology", "face", contacts, ("a", "a", "b"), ("b", "c", "c")),
    )


def _rows(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family)
    return np.column_stack([table.node_a[rows], table.node_b[rows]])


def _read(request: MeshRequest, edge_labels: dict[str, np.ndarray], *, lines=()) -> MeshRequest:
    """The triangles of *request* as a triangulation to read, with its labelled edge groups."""
    triangulated = triangulate_request(request)
    triangulation = InputTriangulation(
        triangulated.mesh.vertices, np.asarray(triangulated.mesh.flat_connectivity), edge_labels
    )
    return dataclasses.replace(request, lines=lines, input_triangulation=triangulation)


def _fed_back(request: MeshRequest, labels: bool) -> tuple[MeshRequest, PlanarCellMesh]:
    """The triangulation of *request* handed back as an input, with or without its groups."""
    triangulated = triangulate_request(request)
    generated = TriangleMeshEngine().assemble(triangulated)
    edge_labels = {}
    if labels:
        geology = triangulated.families.get("geology")
        pairs = np.column_stack([geology.node_a, geology.node_b])
        edge_labels = {
            "river::trace": _rows(generated, "rivers"),
            "interface::a::b": pairs[geology.line == 0],
            "interface::a::c": pairs[geology.line == 1],
            "interface::b::c": pairs[geology.line == 2],
        }
    triangulation = InputTriangulation(
        generated.mesh.vertices, np.asarray(generated.mesh.flat_connectivity), edge_labels
    )
    read = dataclasses.replace(
        request, lines=() if labels else request.lines, input_triangulation=triangulation
    )
    return read, generated


def _zone_of_cells(cell_mesh: PlanarCellMesh) -> np.ndarray:
    names = np.asarray(cell_mesh.zone_names + ("",))
    return names[np.where(cell_mesh.cell_zone >= 0, cell_mesh.cell_zone, len(names) - 1)]


# --------------------------------------------------------------------------- #
# Families of a generated triangulation
# --------------------------------------------------------------------------- #


@needs_gmsh
def test_the_rows_of_a_line_run_along_it_end_to_end() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())
    vertices = cell_mesh.mesh.vertices
    rows = _rows(cell_mesh, "geology")

    assert np.array_equal(rows[1:, 0], rows[:-1, 1])
    assert np.allclose(vertices[rows[0, 0]], CONTACT.coords[0], atol=1e-6)
    assert np.allclose(vertices[rows[-1, 1]], CONTACT.coords[-1], atol=1e-6)
    quality = cell_mesh.qa.families["geology"]
    assert quality["hausdorff_m"] <= 1e-6
    assert quality["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)


@needs_gmsh
def test_a_cell_takes_the_zone_of_its_side_of_the_contact() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())
    x, y = cell_mesh.centers.T
    # The contact runs from (400, 0) to (600, 1000): x = 400 + 0.2 y.
    west = x < X0 + 400 + 0.2 * (y - Y0)
    zones = np.asarray(cell_mesh.zone_names)[cell_mesh.cell_zone]

    assert set(cell_mesh.zone_names) == {"west_unit", "east_unit"}
    assert np.all(zones[west] == "west_unit")
    assert np.all(zones[~west] == "east_unit")


@needs_gmsh
def test_a_line_with_no_edge_has_no_vertex() -> None:
    triangulated = triangulate_request(_square())
    contact = triangulated.families.get("geology")

    assert contact.line_vertices(0).size > 2
    assert contact.line_vertices(len(_square().family("geology").lines)).size == 0


# --------------------------------------------------------------------------- #
# Families of a read triangulation
# --------------------------------------------------------------------------- #


@needs_gmsh
@pytest.mark.parametrize("labels", [True, False], ids=["physical_groups", "line_matching"])
def test_a_read_triangulation_finds_the_families_it_was_generated_with(labels: bool) -> None:
    read, generated = _fed_back(_three_zones(), labels)
    cell_mesh = TriangleMeshEngine().build(read)

    for family in ("rivers", "geology"):
        assert {tuple(sorted(r)) for r in _rows(cell_mesh, family).tolist()} == {
            tuple(sorted(r)) for r in _rows(generated, family).tolist()
        }, family
    assert set(_zone_of_cells(generated).tolist()) == {"a", "b", "c"}
    assert np.array_equal(_zone_of_cells(cell_mesh), _zone_of_cells(generated))
    assert cell_mesh.chains("rivers")


@needs_gmsh
def test_one_interface_group_alone_does_not_say_which_zone_is_on_which_side() -> None:
    request = _square()
    geology = triangulate_request(request).families.get("geology")
    pairs = np.column_stack([geology.node_a, geology.node_b])
    cell_mesh = TriangleMeshEngine().build(
        _read(request, {"interface::east_unit::west_unit": pairs})
    )

    assert cell_mesh.face_rows("geology").any()
    assert np.all(cell_mesh.cell_zone == -1)


@needs_gmsh
def test_a_boundary_group_keeps_its_boundary_edges_and_names_the_edges_it_leaves_out() -> None:
    """A .msh group of the outlet holds the south side and one interior edge drawn by mistake."""
    plain = _square(LineFamilySpec("rivers", "cell", (RIVER,)))
    triangulated = triangulate_request(plain)
    geometry = triangulated.geometry
    vertices = triangulated.mesh.vertices
    outer = geometry.edge_cells[:, 1] < 0
    south = outer & np.all(vertices[geometry.edge_nodes][:, :, 1] == Y0, axis=1)
    north = outer & np.all(vertices[geometry.edge_nodes][:, :, 1] == Y0 + 1000, axis=1)
    interior = np.flatnonzero(~outer)[:1]
    outlet = np.concatenate([geometry.edge_nodes[south], geometry.edge_nodes[interior]])

    cell_mesh = TriangleMeshEngine().build(
        _read(
            plain,
            {
                "boundary::outlet": outlet,
                "boundary::crest": geometry.edge_nodes[north],
                "watershed::outline": geometry.edge_nodes[outer],
            },
        )
    )

    assert cell_mesh.face_rows("boundary:outlet").sum() == south.sum()
    assert cell_mesh.face_rows("boundary:crest").sum() == north.sum()
    assert cell_mesh.face_rows("watershed_boundary").sum() == outer.sum()
    assert np.all(cell_mesh.face_families.cell_b[cell_mesh.face_rows("boundary:outlet")] == -1)
    assert any("boundary:outlet" in note for note in cell_mesh.qa.notes)
    assert not any("boundary:crest" in note for note in cell_mesh.qa.notes)


@needs_gmsh
def test_an_empty_group_of_a_read_triangulation_gives_no_family() -> None:
    plain = _square(LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)))

    cell_mesh = TriangleMeshEngine().build(
        _read(plain, {"river::dry": np.empty((0, 2), dtype=np.int64)})
    )

    assert not cell_mesh.face_rows("rivers").any()
    assert not cell_mesh.chains("rivers")


@needs_gmsh
def test_a_unit_that_borders_one_contact_takes_its_name_from_the_unit_across_it() -> None:
    """Three strips a, b and c: only b borders two groups, so a and c are named from b."""
    contacts = (
        LineString([(X0 + 350, Y0), (X0 + 350, Y0 + 1000)]),
        LineString([(X0 + 650, Y0), (X0 + 650, Y0 + 1000)]),
    )
    request = _square(LineFamilySpec("geology", "face", contacts, ("a", "b"), ("b", "c")))
    geology = triangulate_request(request).families.get("geology")
    pairs = np.column_stack([geology.node_a, geology.node_b])

    cell_mesh = TriangleMeshEngine().build(
        _read(
            request,
            {
                "interface::a::b": pairs[geology.line == 0],
                "interface::b::c": pairs[geology.line == 1],
            },
        )
    )
    x = cell_mesh.centers[:, 0]
    zones = np.asarray(cell_mesh.zone_names)[cell_mesh.cell_zone]

    assert set(zones[x < X0 + 350]) == {"a"}
    assert set(zones[(x > X0 + 350) & (x < X0 + 650)]) == {"b"}
    assert set(zones[x > X0 + 650]) == {"c"}


@needs_gmsh
def test_an_edge_group_that_is_not_made_of_triangle_edges_is_refused() -> None:
    plain = _square(LineFamilySpec("rivers", "cell", (RIVER,)))
    vertices = triangulate_request(plain).mesh.vertices
    corners = [int(np.argmin(vertices.sum(axis=1))), int(np.argmax(vertices.sum(axis=1)))]

    with pytest.raises(MeshGenerationError, match="is not a triangle edge"):
        TriangleMeshEngine().build(_read(plain, {"river::diagonal": np.array([corners])}))


# --------------------------------------------------------------------------- #
# The barrier family around a cutoff wall, wings included
# --------------------------------------------------------------------------- #

ON_LINE_M = 1.0e-3
"""A face node within 1 mm of the wall lies on it."""

_DAM_SIZES = {
    "cell_size": 60.0,
    "river_cell_size": 20.0,
    "lake_refinement": {"cell_size": 30.0, "dam_cell_size": 15.0, "dam_buffer": 60.0},
}


def _planned(
    barriers: tuple[LineString, ...], *, lakes: tuple = (), river: LineString | None = None
) -> MeshRequest:
    """The request the planner makes for a triangle mesh over the reservoir domain."""
    mesh = {"engine": "triangle", **_DAM_SIZES}
    if river is None:
        mesh["families"] = {"rivers": "none"}
    inputs = planning_inputs(
        grid_over(dam.DOMAIN, 10.0, crs_wkt=LAMBERT93_WKT),
        river_trace=None
        if river is None
        else RiverMeshTrace(source_kind="file", crs_wkt=LAMBERT93_WKT, lines=(river,)),
        watershed=dam.DOMAIN,
        lakes=lakes,
        synthetic=False,
        barriers=barriers,
    )
    return plan_mesh_request(MeshConfig.model_validate(mesh), inputs)


@functools.cache
def _walled(offset: float) -> tuple[SnappedWall, MeshRequest, PlanarCellMesh]:
    """The wall *offset* m downstream of the dam shore, laid on it, its request and its mesh."""
    wall = snap_wall_to_shore(dam.reservoir(), dam.trace(offset), 50.0)
    request = _planned((wall.line,), lakes=(wall.polygon,))
    return wall, request, registry.create("triangle").build(request)


def _river_crossing(angle_deg: float) -> tuple[LineString, LineString]:
    centre = np.array([dam.X0 + 600.0, dam.Y0 + 400.0])
    tangent = np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])
    barrier = LineString([centre - 250.0 * tangent, centre + 250.0 * tangent])
    river = LineString(
        [
            (dam.X0 + 50.0, dam.Y0 + 410.0),
            (dam.X0 + 600.0, dam.Y0 + 400.0),
            (dam.X0 + 1150.0, dam.Y0 + 380.0),
        ]
    )
    return barrier, river


def _interior_rows(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
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


def _midpoints(cell_mesh: PlanarCellMesh, rows: np.ndarray) -> np.ndarray:
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    return 0.5 * (vertices[rows[:, 2]] + vertices[rows[:, 3]])


@needs_gmsh
@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_the_wall_faces_lie_on_the_wall_line(offset: float) -> None:
    _, request, cell_mesh = _walled(offset)
    line = request.family(BARRIER_FAMILY).lines[0]
    rows = _interior_rows(cell_mesh, BARRIER_FAMILY)
    qa = cell_mesh.qa.families[BARRIER_FAMILY]

    assert _node_gap(cell_mesh, rows, line) < ON_LINE_M
    assert qa["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert qa["mixed_cells"] == 0.0


@needs_gmsh
@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_each_shore_face_is_one_face_of_both_families(offset: float) -> None:
    wall, _, cell_mesh = _walled(offset)
    barrier = _pairs(_interior_rows(cell_mesh, BARRIER_FAMILY))
    lakes = _pairs(_interior_rows(cell_mesh, "lakes"))
    shared = set(barrier) & set(lakes)
    rows = _interior_rows(cell_mesh, BARRIER_FAMILY)
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


@needs_gmsh
@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_every_barrier_row_keeps_the_lake_on_its_left(offset: float) -> None:
    wall, _, cell_mesh = _walled(offset)
    rows = _interior_rows(cell_mesh, BARRIER_FAMILY)
    lake = shapely.contains_xy(wall.polygon, *cell_mesh.centers.T)

    assert not downstream_of_wall(wall.line, cell_mesh.centers[rows[:, 0]]).any()
    assert downstream_of_wall(wall.line, cell_mesh.centers[rows[:, 1]]).sum() >= len(rows) // 2
    assert not lake[rows[:, 1]].any()


@needs_gmsh
@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_the_wings_meet_the_shore_at_its_corners_and_reach_their_ends(offset: float) -> None:
    wall, request, cell_mesh = _walled(offset)
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    barrier = _interior_rows(cell_mesh, BARRIER_FAMILY)
    lakes = _interior_rows(cell_mesh, "lakes")
    line = request.family(BARRIER_FAMILY).lines[0]

    for corner in (wall.shore.coords[0], wall.shore.coords[-1]):
        node = int(np.argmin(np.hypot(*(vertices - corner).T)))
        assert np.hypot(*(vertices[node] - corner)) < ON_LINE_M
        assert np.count_nonzero(barrier[:, 2:] == node) == 2
        assert np.count_nonzero(lakes[:, 2:] == node) == 2
    for end in (line.coords[0], line.coords[-1]):
        assert np.hypot(*(vertices[barrier[:, 2:].ravel()] - end).T).min() < ON_LINE_M


@needs_gmsh
@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_nothing_reaches_the_lake_side_from_downstream_across_the_family(offset: float) -> None:
    wall, _, cell_mesh = _walled(offset)
    lake = np.flatnonzero(shapely.contains_xy(wall.polygon, *cell_mesh.centers.T))
    faces = [BarrierFace(a, b, 0.0) for a, b in _pairs(_interior_rows(cell_mesh, BARRIER_FAMILY))]

    assert wall_leaks(cell_mesh, wall.line, lake, faces, reach=100.0).size == 0
    assert wall_leaks(cell_mesh, wall.line, lake, faces[::2], reach=100.0).size > 0


@needs_gmsh
@pytest.mark.parametrize("angle", [90.0, 30.0, 15.0])
def test_a_river_crosses_the_barrier_once_between_two_chain_cells(angle: float) -> None:
    barrier, river = _river_crossing(angle)
    request = _planned((barrier,), river=river)
    cell_mesh = registry.create("triangle").build(request)
    (chain,) = cell_mesh.chains("rivers")
    links = {
        tuple(sorted(link))
        for link in zip(chain.cell_ids[:-1].tolist(), chain.cell_ids[1:].tolist(), strict=True)
        if link[0] != link[1]
    }
    faces = set(_pairs(_interior_rows(cell_mesh, BARRIER_FAMILY)))
    qa = cell_mesh.qa.families

    assert len(links & faces) == 1
    assert qa["rivers"]["breaks"] == 0.0
    assert qa[BARRIER_FAMILY]["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert _node_gap(cell_mesh, _interior_rows(cell_mesh, BARRIER_FAMILY), barrier) < ON_LINE_M


# --------------------------------------------------------------------------- #
# The fan around a vertex, which joins the cells of a chain
# --------------------------------------------------------------------------- #

_FAN_VERTICES = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.5]])
_FAN_TRIANGLES = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
"""A square cut into four triangles around its centre, vertex 4."""


def test_the_fan_around_an_inner_vertex_gives_the_triangles_between_two_edges() -> None:
    lookup = edge_lookup(_FAN_VERTICES, _FAN_TRIANGLES)
    start = int(lookup.cell_left_of(np.array([0]), np.array([4]))[0])

    assert lookup.fan(start, 4, 2) == [2]


def test_the_fan_around_a_corner_of_the_domain_stops_at_the_boundary() -> None:
    lookup = edge_lookup(_FAN_VERTICES, _FAN_TRIANGLES)
    start = int(lookup.cell_left_of(np.array([4]), np.array([0]))[0])

    assert lookup.fan(start, 0, 3) == []


@settings(max_examples=50, deadline=None, derandomize=True)
@given(
    st.lists(
        st.tuples(st.integers(0, 1000), st.integers(0, 1000)), min_size=4, max_size=40, unique=True
    )
)
def test_each_edge_of_a_triangle_finds_that_triangle_on_its_left(points) -> None:
    """Whatever the order of its corners, a triangle is read counter-clockwise."""
    vertices = np.asarray(points, dtype=float)
    assume(np.linalg.matrix_rank(vertices[1:] - vertices[0]) == 2)
    triangles = Delaunay(vertices).simplices
    corners = vertices[triangles]
    first, second = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
    twice_area = first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]
    triangles = triangles[np.abs(twice_area) > 1.0e-9]
    assume(len(triangles) > 0)

    lookup = edge_lookup(vertices, triangles)

    cells = np.arange(len(triangles))
    for k in range(3):
        start, stop = lookup.ccw[:, k], lookup.ccw[:, (k + 1) % 3]
        assert np.array_equal(lookup.cell_left_of(start, stop), cells)
        right = lookup.cell_left_of(stop, start)
        assert np.all(right != cells)
