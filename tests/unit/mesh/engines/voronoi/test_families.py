"""Families read on generated voronoi meshes: river chains, face rows, box sides and zones.

Each mesh comes from ``VoronoiMeshEngine`` on a catchment of 400 m by 300 m at
20 m, its lines resampled as the planner does, so every build first passes the
gates G0 to G6. The dam cases mesh the reservoir of ``tests/_helpers/reservoir_dam.py``
around its cutoff wall, through the planner.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import BARRIER_FAMILY, LineFamilySpec, MeshRequest
from hydromodpy.mesh.resample import resample_families
from hydromodpy.model.boundaries.cutoff_wall_shore import SnappedWall
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over, mesh_request, uniform_size_field

X0, Y0 = L93_ORIGIN
H = 20.0
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)
ON_LINE_M = 1.0e-3
"""The gate G2 puts a pair face within 1 mm of its segment ends."""

SIDES = ("west", "east", "south", "north")


def line(*points: tuple[float, float]) -> LineString:
    """A line given in meters from the domain corner."""
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def contact(*lines: LineString) -> LineFamilySpec:
    return LineFamilySpec(
        "geology",
        "face",
        lines,
        zone_left=tuple(f"l{k}" for k in range(len(lines))),
        zone_right=tuple(f"r{k}" for k in range(len(lines))),
    )


def rivers(*lines: LineString) -> LineFamilySpec:
    return LineFamilySpec("rivers", "cell", lines)


def request_of(*families: LineFamilySpec, domain: Polygon = DOMAIN) -> MeshRequest:
    """The request of the families on a 5 m grid, resampled at ``H`` like the planner does."""
    grid = grid_over(DOMAIN, 5.0)
    field = uniform_size_field(grid, H)
    lines = resample_families(families, domain=domain, size_field=field).families
    return mesh_request(grid, domain=domain, nominal_size_m=H, lines=lines, size_field=field)


def build(*families: LineFamilySpec, domain: Polygon = DOMAIN) -> PlanarCellMesh:
    """Mesh the families with the voronoi engine. The gates raise on any fault."""
    return VoronoiMeshEngine().build(request_of(*families, domain=domain))


def vertices_of(cell_mesh: PlanarCellMesh) -> np.ndarray:
    return np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]


def rows_of(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    return np.flatnonzero(cell_mesh.face_rows(family))


def side_of(line_: LineString, points: np.ndarray) -> np.ndarray:
    """Cross product sign of each point against the first-to-last chord of a straight line."""
    coords = shapely.get_coordinates(line_)
    tangent, reach = coords[-1] - coords[0], points - coords[0]
    return tangent[0] * reach[:, 1] - tangent[1] * reach[:, 0]


def assert_faces_on_lines(cell_mesh: PlanarCellMesh, request: MeshRequest, family: str) -> None:
    """Every row of a face family lies on its request lines within 1 mm."""
    table = cell_mesh.face_families
    rows = rows_of(cell_mesh, family)
    ends = vertices_of(cell_mesh)[np.concatenate([table.node_a[rows], table.node_b[rows]])]
    source = shapely.multilinestrings(list(request.family(family).lines))
    assert shapely.distance(shapely.points(ends), source).max() < ON_LINE_M


def crossing_families() -> tuple[LineFamilySpec, ...]:
    angle = math.radians(60.0)
    centre = np.array([200.0, 150.0])
    tangent = np.array([math.cos(angle), math.sin(angle)])
    face = line(tuple(centre - 160.0 * tangent), tuple(centre + 160.0 * tangent))
    return rivers(line((20.0, 150.0), (380.0, 150.0))), contact(face)


@functools.cache
def crossing() -> tuple[MeshRequest, PlanarCellMesh]:
    request = request_of(*crossing_families())
    return request, VoronoiMeshEngine().build(request)


def test_a_river_crossing_a_contact_runs_through_the_pair() -> None:
    request, cell_mesh = crossing()
    (chain,) = cell_mesh.chains("rivers")
    table = cell_mesh.face_families
    rows = rows_of(cell_mesh, "geology")
    pair = chain.cell_ids[chain.offset_m > 0.0]
    faces = {
        tuple(sorted(cells)) for cells in zip(table.cell_a[rows], table.cell_b[rows], strict=True)
    }
    qa = cell_mesh.qa.families

    assert pair.size == 2
    assert tuple(sorted(pair.tolist())) in faces
    assert qa["rivers"]["breaks"] == 0.0
    assert chain.offset_m[chain.offset_m > 0.0] == pytest.approx(
        np.full(2, qa["rivers"]["crossing_offset_m_max"])
    )
    assert_faces_on_lines(cell_mesh, request, "geology")
    assert qa["geology"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("vertical_end, degree", [(150.0, 3), (20.0, 4)], ids=["t", "x"])
def test_t_and_x_junctions_keep_every_segment(vertical_end: float, degree: int) -> None:
    request = request_of(
        contact(line((50.0, 150.0), (350.0, 150.0)), line((200.0, 280.0), (200.0, vertical_end)))
    )
    cell_mesh = VoronoiMeshEngine().build(request)
    geology = cell_mesh.qa.families["geology"]
    table = cell_mesh.face_families
    rows = rows_of(cell_mesh, "geology")
    vertices = vertices_of(cell_mesh)
    node = int(np.argmin(np.hypot(*(vertices - (X0 + 200.0, Y0 + 150.0)).T)))

    assert geology["conformal_length_share"] == 1.0
    assert geology["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert np.hypot(*(vertices[node] - (X0 + 200.0, Y0 + 150.0))) < ON_LINE_M
    assert np.count_nonzero((table.node_a[rows] == node) | (table.node_b[rows] == node)) == degree
    assert_faces_on_lines(cell_mesh, request, "geology")


def test_a_free_end_face_runs_to_the_end() -> None:
    cell_mesh = build(contact(line((100.0, 150.0), (300.0, 150.0))))
    geology = cell_mesh.qa.families["geology"]
    assert geology["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert geology["mixed_cells"] == 0.0


def test_a_free_end_whose_tip_left_the_domain_is_not_counted_as_followed() -> None:
    geology = build(contact(line((200.0, 60.0), (200.0, 295.0)))).qa.families["geology"]
    assert geology["free_ends"] == 1.0
    assert geology["conformal_length_share"] < 1.0
    assert geology["covered_length_rel"] < 1.0


def test_a_hole_touching_the_outer_ring_stops_at_gate_g4_and_says_why() -> None:
    diamond = [(X0 + x, Y0 + y) for x, y in ((100, 0), (180, 60), (100, 120), (20, 60))]
    pinched = Polygon(DOMAIN.exterior.coords, holes=[diamond])
    with pytest.raises(MeshGenerationError, match=r"G4.*touching another ring"):
        build(domain=pinched)


def test_a_contact_ending_on_the_boundary_reaches_it() -> None:
    request = request_of(contact(line((200.0, 0.0), (200.0, 200.0))))
    cell_mesh = VoronoiMeshEngine().build(request)
    geology = cell_mesh.qa.families["geology"]
    assert geology["boundary_ends"] == 1.0
    assert geology["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert_faces_on_lines(cell_mesh, request, "geology")


def test_a_lake_ring_with_a_sharp_turn_is_one_closed_face() -> None:
    ring = line((100.0, 100.0), (300.0, 100.0), (260.0, 200.0), (150.0, 230.0), (100.0, 100.0))
    request = request_of(LineFamilySpec("lakes", "face", (ring,), closed=True))
    cell_mesh = VoronoiMeshEngine().build(request)
    lakes = cell_mesh.qa.families["lakes"]
    assert lakes["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert lakes["mixed_cells"] == 0.0
    assert_faces_on_lines(cell_mesh, request, "lakes")


ROUND = shapely.Point(X0 + 200.0, Y0 + 150.0).buffer(140.0, 32)
"""A round catchment: no edge of its ring lies on a side of its box."""


def test_a_round_catchment_names_its_lines_and_no_box_side() -> None:
    cell_mesh = build(contact(line((100.0, 150.0), (300.0, 150.0))), domain=ROUND)
    assert cell_mesh.face_families.names == ("geology",)


def test_a_round_catchment_without_lines_has_no_face_family() -> None:
    assert build(domain=ROUND).face_families is None


WallMesh = Callable[[float], tuple[SnappedWall, MeshRequest, PlanarCellMesh]]
OFFSETS = pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
"""A wall trace 12 m downstream of the dam shore, and one that crosses the lake."""


def interior_rows(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """``(cell_a, cell_b, node_a, node_b)`` of the interior rows of one family."""
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family) & (table.cell_b >= 0)
    return np.column_stack(
        [table.cell_a[rows], table.cell_b[rows], table.node_a[rows], table.node_b[rows]]
    )


def cell_pairs(rows: np.ndarray) -> list[tuple[int, int]]:
    return [tuple(pair) for pair in np.sort(rows[:, :2], axis=1).tolist()]


@OFFSETS
def test_the_wall_faces_lie_on_the_wall_line(
    offset: float, walled_reservoir_mesh: WallMesh
) -> None:
    _, request, cell_mesh = walled_reservoir_mesh(offset)
    rows = interior_rows(cell_mesh, BARRIER_FAMILY)
    nodes = shapely.points(vertices_of(cell_mesh)[rows[:, 2:].ravel()])
    qa = cell_mesh.qa.families[BARRIER_FAMILY]

    assert shapely.distance(nodes, request.family(BARRIER_FAMILY).lines[0]).max() < ON_LINE_M
    assert qa["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert qa["mixed_cells"] == 0.0
