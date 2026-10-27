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
from hydromodpy.physics.flow.cutoff_wall_shore import SnappedWall
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.flow_barrier import BarrierFace, downstream_of_wall, wall_leaks
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec, MeshRequest
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over, mesh_request, uniform_size_field

X0, Y0 = L93_ORIGIN
H = 20.0
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)
ON_LINE_M = 1.0e-3
"""The gate G2 puts a pair face within 1 mm of its segment ends."""

SIDES = ("west", "east", "south", "north")


def line(*points: tuple[float, float]) -> LineString:
    """A line given in metres from the domain corner."""
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


def test_the_pair_cells_of_a_contact_take_its_zones() -> None:
    _, cell_mesh = crossing()
    table = cell_mesh.face_families
    zones = cell_mesh.cell_zone
    rows = rows_of(cell_mesh, "geology")
    left = cell_mesh.zone_names.index("l0")
    right = cell_mesh.zone_names.index("r0")
    paired = np.zeros(cell_mesh.n_cells, dtype=bool)
    paired[np.concatenate([table.cell_a[rows], table.cell_b[rows]])] = True

    assert np.all(table.zone_left[rows] == left) and np.all(table.zone_right[rows] == right)
    assert np.all(zones[table.cell_a[rows]] == left)
    assert np.all(zones[table.cell_b[rows]] == right)
    assert np.all(zones[~paired] == -1)


def test_a_contact_across_the_domain_splits_it_in_two_zones() -> None:
    request = request_of(contact(line((180.0, 0.0), (220.0, 300.0))))
    cell_mesh = VoronoiMeshEngine().build(request)
    side = side_of(request.family("geology").lines[0], cell_mesh.centers)

    assert np.all(cell_mesh.cell_zone[side > 0.0] == cell_mesh.zone_names.index("l0"))
    assert np.all(cell_mesh.cell_zone[side < 0.0] == cell_mesh.zone_names.index("r0"))


def test_a_river_that_makes_a_contact_yield_leaves_only_its_mixed_cells_unnamed() -> None:
    angle = math.radians(50.0)
    centre = np.array([200.0, 150.0])
    tangent = np.array([math.cos(angle), math.sin(angle)])
    river = line(tuple(centre - 190.0 * tangent), tuple(centre + 190.0 * tangent))
    request = request_of(rivers(river), contact(line((180.0, 0.0), (220.0, 300.0))))
    cell_mesh = VoronoiMeshEngine().build(request)
    geology = cell_mesh.qa.families["geology"]
    zones = cell_mesh.cell_zone
    named = zones >= 0
    side = side_of(request.family("geology").lines[0], cell_mesh.centers)

    assert geology["yielded_segments"] + geology["merged_circles"] > 0
    assert np.count_nonzero(~named) == geology["mixed_cells"] > 0
    assert np.all(zones[named & (side > 0.0)] == cell_mesh.zone_names.index("l0"))
    assert np.all(zones[named & (side < 0.0)] == cell_mesh.zone_names.index("r0"))


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


def test_an_acute_junction_counts_its_mixed_cells() -> None:
    angle = math.radians(15.0)
    tip = (50.0 + 300.0 * math.cos(angle), 100.0 + 300.0 * math.sin(angle))
    cell_mesh = build(contact(line((50.0, 100.0), (350.0, 100.0)), line((50.0, 100.0), tip)))
    geology = cell_mesh.qa.families["geology"]

    assert geology["merged_circles"] > 0
    assert geology["mixed_cells"] > 0
    assert np.count_nonzero(cell_mesh.cell_zone < 0) > 0


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


def test_a_contact_meeting_the_boundary_at_20_degrees_still_builds() -> None:
    angle = math.radians(20.0)
    end = (100.0 + 250.0 * math.cos(angle), 250.0 * math.sin(angle))
    geology = build(contact(line((100.0, 0.0), end))).qa.families["geology"]
    assert geology["merged_circles"] + geology["yielded_segments"] > 0


def test_two_close_thalwegs_share_cells_and_stay_continuous() -> None:
    cell_mesh = build(
        rivers(line((20.0, 150.0), (380.0, 150.0)), line((20.0, 158.0), (380.0, 158.0)))
    )
    assert cell_mesh.qa.families["rivers"]["shared_cells"] > 0
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def test_a_confluence_cell_is_in_three_chains() -> None:
    cell_mesh = build(
        rivers(
            line((50.0, 250.0), (200.0, 150.0)),
            line((350.0, 250.0), (200.0, 150.0)),
            line((200.0, 150.0), (200.0, 20.0)),
        )
    )
    chains = cell_mesh.chains("rivers")
    common = set(chains[0].cell_ids.tolist())
    for chain in chains[1:]:
        common &= set(chain.cell_ids.tolist())
    assert len(common) == 1
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def test_a_lake_ring_with_a_sharp_turn_is_one_closed_face() -> None:
    ring = line((100.0, 100.0), (300.0, 100.0), (260.0, 200.0), (150.0, 230.0), (100.0, 100.0))
    request = request_of(LineFamilySpec("lakes", "face", (ring,), closed=True))
    cell_mesh = VoronoiMeshEngine().build(request)
    lakes = cell_mesh.qa.families["lakes"]
    assert lakes["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert lakes["mixed_cells"] == 0.0
    assert_faces_on_lines(cell_mesh, request, "lakes")


def test_box_sides_are_boundary_families_with_the_cell_on_the_left() -> None:
    cell_mesh = build(contact(line((100.0, 150.0), (300.0, 150.0))))
    table = cell_mesh.face_families
    vertices = vertices_of(cell_mesh)
    for side in SIDES:
        rows = rows_of(cell_mesh, f"boundary:{side}")
        tangent = vertices[table.node_b[rows]] - vertices[table.node_a[rows]]
        reach = cell_mesh.centers[table.cell_a[rows]] - vertices[table.node_a[rows]]
        assert rows.size > 0
        assert np.all(table.cell_b[rows] == -1)
        assert np.all(tangent[:, 0] * reach[:, 1] - tangent[:, 1] * reach[:, 0] >= 0.0)
    named = sum(rows_of(cell_mesh, f"boundary:{side}").size for side in SIDES)
    assert named == np.count_nonzero(cell_mesh.geometry.edge_cells[:, 1] < 0)


ROUND = shapely.Point(X0 + 200.0, Y0 + 150.0).buffer(140.0, 32)
"""A round catchment: no edge of its ring lies on a side of its box."""


def test_a_round_catchment_names_its_lines_and_no_box_side() -> None:
    cell_mesh = build(contact(line((100.0, 150.0), (300.0, 150.0))), domain=ROUND)
    assert cell_mesh.face_families.names == ("geology",)


def test_a_round_catchment_without_lines_has_no_face_family() -> None:
    assert build(domain=ROUND).face_families is None


def test_a_mesh_without_lines_has_sides_only_and_no_zones() -> None:
    cell_mesh = build()
    assert all(name.startswith("boundary:") for name in cell_mesh.face_families.names)
    assert cell_mesh.cell_zone is None
    assert cell_mesh.cell_chains == ()


def test_permuted_input_gives_the_same_mesh() -> None:
    face_a = line((50.0, 100.0), (350.0, 120.0))
    face_b = line((100.0, 20.0), (130.0, 280.0))
    river_a = line((20.0, 200.0), (380.0, 210.0))
    river_b = line((300.0, 290.0), (250.0, 205.4))
    one = build(rivers(river_a, river_b), contact(face_a, face_b))
    two = build(
        LineFamilySpec("geology", "face", (face_b, face_a), ("l1", "l0"), ("r1", "r0")),
        rivers(river_b, river_a),
    )
    assert np.array_equal(one.mesh.vertices, two.mesh.vertices)
    assert np.array_equal(one.centers, two.centers)
    assert np.array_equal(one.geometry.padded_connectivity, two.geometry.padded_connectivity)
    assert [c.cell_ids.tolist() for c in one.cell_chains] == [
        c.cell_ids.tolist() for c in two.cell_chains
    ]
    assert np.array_equal(one.face_families.cell_a, two.face_families.cell_a)
    assert np.array_equal(one.cell_zone, two.cell_zone)


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


@OFFSETS
def test_each_shore_face_is_one_face_of_both_families(
    offset: float, walled_reservoir_mesh: WallMesh
) -> None:
    wall, _, cell_mesh = walled_reservoir_mesh(offset)
    rows = interior_rows(cell_mesh, BARRIER_FAMILY)
    barrier = cell_pairs(rows)
    lakes = cell_pairs(interior_rows(cell_mesh, "lakes"))
    vertices = vertices_of(cell_mesh)
    middle = 0.5 * (vertices[rows[:, 2]] + vertices[rows[:, 3]])
    on_shore = np.asarray(barrier)[shapely.distance(shapely.points(middle), wall.shore) < ON_LINE_M]
    shared = set(barrier) & set(lakes)

    assert len(barrier) == len(set(barrier))
    assert len(lakes) == len(set(lakes))
    assert len(shared) >= 5
    assert {tuple(pair) for pair in on_shore.tolist()} <= shared


@OFFSETS
def test_every_barrier_row_keeps_the_lake_on_its_left(
    offset: float, walled_reservoir_mesh: WallMesh
) -> None:
    wall, _, cell_mesh = walled_reservoir_mesh(offset)
    rows = interior_rows(cell_mesh, BARRIER_FAMILY)
    lake = shapely.contains_xy(wall.polygon, *cell_mesh.centers.T)

    assert not downstream_of_wall(wall.line, cell_mesh.centers[rows[:, 0]]).any()
    assert downstream_of_wall(wall.line, cell_mesh.centers[rows[:, 1]]).sum() >= len(rows) // 2
    assert not lake[rows[:, 1]].any()


@OFFSETS
def test_the_wings_meet_the_shore_at_its_corners_and_reach_their_ends(
    offset: float, walled_reservoir_mesh: WallMesh
) -> None:
    wall, request, cell_mesh = walled_reservoir_mesh(offset)
    vertices = vertices_of(cell_mesh)
    barrier = interior_rows(cell_mesh, BARRIER_FAMILY)
    lakes = interior_rows(cell_mesh, "lakes")
    wall_line = request.family(BARRIER_FAMILY).lines[0]

    for corner in (wall.shore.coords[0], wall.shore.coords[-1]):
        node = int(np.argmin(np.hypot(*(vertices - corner).T)))
        assert np.hypot(*(vertices[node] - corner)) < ON_LINE_M
        assert np.count_nonzero(barrier[:, 2:] == node) == 2
        assert np.count_nonzero(lakes[:, 2:] == node) == 2
    for end in (wall_line.coords[0], wall_line.coords[-1]):
        assert np.hypot(*(vertices[barrier[:, 2:].ravel()] - end).T).min() < ON_LINE_M


@OFFSETS
def test_nothing_reaches_the_lake_side_from_downstream_across_the_family(
    offset: float, walled_reservoir_mesh: WallMesh
) -> None:
    wall, _, cell_mesh = walled_reservoir_mesh(offset)
    lake = np.flatnonzero(shapely.contains_xy(wall.polygon, *cell_mesh.centers.T))
    faces = [
        BarrierFace(a, b, 0.0) for a, b in cell_pairs(interior_rows(cell_mesh, BARRIER_FAMILY))
    ]

    assert wall_leaks(cell_mesh, wall.line, lake, faces, reach=100.0).size == 0
    assert wall_leaks(cell_mesh, wall.line, lake, faces[::2], reach=100.0).size > 0
