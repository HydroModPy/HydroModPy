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
from shapely.geometry import LineString

from hydromodpy.catchment.algorithms.river_mesh_trace import RiverMeshTrace
from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.mesh import registry
from hydromodpy.mesh.engines.face_families import edge_lookup
from hydromodpy.mesh.engines.triangle.engine import (
    TriangleMeshEngine,
    triangulate_request,
)
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import (
    BARRIER_FAMILY,
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
)
from hydromodpy.model.boundaries.cutoff_wall_shore import SnappedWall, snap_wall_to_shore
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


def _rows(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family)
    return np.column_stack([table.node_a[rows], table.node_b[rows]])


def _read(request: MeshRequest, edge_labels: dict[str, np.ndarray], *, lines=()) -> MeshRequest:
    """The triangles of *request* as a triangulation to read, with its labeled edge groups."""
    triangulated = triangulate_request(request)
    triangulation = InputTriangulation(
        triangulated.mesh.vertices, np.asarray(triangulated.mesh.flat_connectivity), edge_labels
    )
    return dataclasses.replace(request, lines=lines, input_triangulation=triangulation)


@needs_gmsh
def test_rows_run_along_the_line() -> None:
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
def test_line_without_edge_has_no_vertex() -> None:
    triangulated = triangulate_request(_square())
    contact = triangulated.families.get("geology")

    assert contact.line_vertices(0).size > 2
    assert contact.line_vertices(len(_square().family("geology").lines)).size == 0


@needs_gmsh
def test_boundary_group_of_a_msh() -> None:
    # A .msh group of the outlet holds the south side and one interior edge drawn by mistake.
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
def test_empty_group_gives_no_family() -> None:
    plain = _square(LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)))

    cell_mesh = TriangleMeshEngine().build(
        _read(plain, {"river::dry": np.empty((0, 2), dtype=np.int64)})
    )

    assert not cell_mesh.face_rows("rivers").any()
    assert not cell_mesh.chains("rivers")


def _three_strips() -> tuple[MeshRequest, np.ndarray, np.ndarray]:
    """Three strips a, b and c with two contacts, and the edges of each contact group."""
    contacts = (
        LineString([(X0 + 350, Y0), (X0 + 350, Y0 + 1000)]),
        LineString([(X0 + 650, Y0), (X0 + 650, Y0 + 1000)]),
    )
    request = _square(LineFamilySpec("geology", "face", contacts, ("a", "b"), ("b", "c")))
    geology = triangulate_request(request).families.get("geology")
    pairs = np.column_stack([geology.node_a, geology.node_b])
    return request, pairs[geology.line == 0], pairs[geology.line == 1]


def _zones_of_strips(cell_mesh: PlanarCellMesh) -> list[set[str]]:
    x = cell_mesh.centers[:, 0]
    zones = np.asarray(cell_mesh.zone_names)[cell_mesh.cell_zone]
    return [
        set(zones[x < X0 + 350]),
        set(zones[(x > X0 + 350) & (x < X0 + 650)]),
        set(zones[x > X0 + 650]),
    ]


@needs_gmsh
def test_unit_named_from_the_unit_across() -> None:
    # Three strips a, b and c. Only b borders two groups, so a and c are named from b.
    request, a_b, b_c = _three_strips()

    cell_mesh = TriangleMeshEngine().build(
        _read(request, {"interface::a::b": a_b, "interface::b::c": b_c})
    )

    assert _zones_of_strips(cell_mesh) == [{"a"}, {"b"}, {"c"}]


@needs_gmsh
def test_interface_edge_on_the_outline_names_no_unit() -> None:
    # A stray edge of the south side of strip a in the a::b group has no cell across it. It adds no zone.
    request, a_b, b_c = _three_strips()
    geometry = triangulate_request(request).geometry
    vertices = triangulate_request(request).mesh.vertices
    outer = geometry.edge_cells[:, 1] < 0
    ends = vertices[geometry.edge_nodes]
    in_strip_a = (
        outer & np.all(ends[:, :, 1] == Y0, axis=1) & np.all(ends[:, :, 0] < X0 + 350, axis=1)
    )
    stray = geometry.edge_nodes[np.flatnonzero(in_strip_a)[:1]]

    cell_mesh = TriangleMeshEngine().build(
        _read(
            request,
            {"interface::a::b": np.concatenate([a_b, stray]), "interface::b::c": b_c},
        )
    )

    assert _zones_of_strips(cell_mesh) == [{"a"}, {"b"}, {"c"}]
    geology = cell_mesh.face_families
    assert (geology.cell_b[cell_mesh.face_rows("geology")] < 0).sum() == 1


@needs_gmsh
def test_refusals() -> None:
    plain = _square(LineFamilySpec("rivers", "cell", (RIVER,)))
    vertices = triangulate_request(plain).mesh.vertices
    corners = [int(np.argmin(vertices.sum(axis=1))), int(np.argmax(vertices.sum(axis=1)))]

    with pytest.raises(MeshGenerationError, match="is not a triangle edge"):
        TriangleMeshEngine().build(_read(plain, {"river::diagonal": np.array([corners])}))


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
    return wall, request, registry.mesh_engines.create("triangle").build(request)


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


@needs_gmsh
@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_wall_faces_on_the_line(offset: float) -> None:
    _, request, cell_mesh = _walled(offset)
    line = request.family(BARRIER_FAMILY).lines[0]
    rows = _interior_rows(cell_mesh, BARRIER_FAMILY)
    qa = cell_mesh.qa.families[BARRIER_FAMILY]

    assert _node_gap(cell_mesh, rows, line) < ON_LINE_M
    assert qa["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert qa["mixed_cells"] == 0.0


@needs_gmsh
@pytest.mark.parametrize("angle", [90.0, 30.0, 15.0])
def test_river_crosses_barrier_once(angle: float) -> None:
    barrier, river = _river_crossing(angle)
    request = _planned((barrier,), river=river)
    cell_mesh = registry.mesh_engines.create("triangle").build(request)
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


_FAN_VERTICES = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.5]])
_FAN_TRIANGLES = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
"""A square cut into four triangles around its center, vertex 4."""


def test_fan_stops_at_the_boundary() -> None:
    lookup = edge_lookup(_FAN_VERTICES, _FAN_TRIANGLES)
    start = int(lookup.cell_left_of(np.array([4]), np.array([0]))[0])

    assert lookup.fan(start, 0, 3) == []
