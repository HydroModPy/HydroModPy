"""Placement of the constraint seeds: chains, mirror pairs, crossings, boundary."""

from __future__ import annotations

import math

import numpy as np
import pytest
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.engines.voronoi.constraints import (
    ConstraintPlan,
    SeedRole,
    place_constraints,
)
from hydromodpy.spatial.mesh.engines.voronoi.frame import SizeSampler, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.gates import BALL_SHRINK
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest
from tests.unit.mesh.engines.voronoi.core_pipeline import WKT, X0, Y0, size_field

H = 20.0
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)


def line(*points: tuple[float, float]) -> LineString:
    """A line given in metres from the domain corner."""
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def contact(*lines: LineString, name: str = "geology") -> LineFamilySpec:
    """A face family whose lines separate zones ``l<k>`` and ``r<k>``."""
    return LineFamilySpec(
        name,
        "face",
        lines,
        zone_left=tuple(f"l{k}" for k in range(len(lines))),
        zone_right=tuple(f"r{k}" for k in range(len(lines))),
    )


def rivers(*lines: LineString) -> LineFamilySpec:
    return LineFamilySpec("rivers", "cell", lines)


def plan_of(
    *families: LineFamilySpec, domain: Polygon = DOMAIN, resample: bool = True
) -> ConstraintPlan:
    """The constraint plan of the families, resampled at ``H`` like the planner does."""
    field = size_field(domain, 5.0, H)
    if resample:
        families = resample_families(families, domain=domain, size_field=field).families
    request = MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=field.grid,
        nominal_size_m=H,
        lines=families,
        size_field=field,
    )
    frame = local_frame(domain)
    return place_constraints(request, frame, SizeSampler(field, frame))


def assert_definition_2(plan: ConstraintPlan) -> None:
    """No constraint seed lies inside the ball of a conformal vertex."""
    balls = plan.berge_balls()
    if not len(balls.radius):
        return
    found = cKDTree(plan.seeds.xy).query_ball_point(balls.center, balls.radius * (1 - BALL_SHRINK))
    assert all(not hits for hits in found)


def crossing_plan() -> ConstraintPlan:
    angle = math.radians(60.0)
    centre = np.array([200.0, 150.0])
    tangent = np.array([math.cos(angle), math.sin(angle)])
    face = line(tuple(centre - 160.0 * tangent), tuple(centre + 160.0 * tangent))
    return plan_of(rivers(line((20.0, 150.0), (380.0, 150.0))), contact(face))


def test_seeds_come_chains_first_then_faces_then_the_boundary() -> None:
    plan = crossing_plan()
    role = plan.seeds.role
    block = np.where(
        role == SeedRole.CHAIN,
        0,
        np.where((role == SeedRole.BOUNDARY) & (plan.seeds.vertex_id < 0), 2, 1),
    )
    assert np.all(np.diff(block) >= 0)
    assert set(block.tolist()) == {0, 1, 2}


def test_protection_radius_is_the_local_size() -> None:
    plan = crossing_plan()
    assert plan.seeds.radius == pytest.approx(np.full(plan.seeds.n, H))


def test_a_crossing_puts_its_pair_in_the_chain_with_the_offset_computed_by_hand() -> None:
    plan = crossing_plan()
    (chain,) = plan.chains
    mirror = np.flatnonzero(plan.seeds.role[chain.seed_ids] == SeedRole.MIRROR)
    assert mirror.tolist() == [mirror[0], mirror[0] + 1]
    assert plan.family_stats["rivers"]["crossings"] == 1.0
    faces = plan.faces
    segment = int(plan.seeds.pair_id[chain.seed_ids[mirror[0]]])
    a, b = faces.segment_nodes[segment]
    start, stop = faces.vertices[a], faces.vertices[b]
    d = float(np.hypot(*(stop - start)))
    r_a, r_b = faces.radius[a], faces.radius[b]
    along = (d**2 + r_a**2 - r_b**2) / (2.0 * d)
    height = math.sqrt(r_a**2 - along**2)
    unit = (stop - start) / d
    foot = start + along * unit
    river_y = shapely.get_coordinates(plan.source_lines["rivers"][0])[0, 1]
    expected = sorted(abs(foot[1] + side * height * unit[0] - river_y) for side in (1.0, -1.0))
    assert sorted(chain.offset_m[mirror]) == pytest.approx(expected, rel=1e-9)
    assert np.all(np.delete(chain.offset_m, mirror) == 0.0)
    upstream = plan.seeds.xy[chain.seed_ids[mirror[0] - 1]] - foot
    first = plan.seeds.xy[chain.seed_ids[mirror[0]]] - foot
    side = unit[0] * first[1] - unit[1] * first[0]
    assert np.sign(side) == np.sign(unit[0] * upstream[1] - unit[1] * upstream[0])
    assert_definition_2(plan)


def test_thalwegs_closer_than_half_a_cell_share_their_cells() -> None:
    plan = plan_of(rivers(line((20.0, 150.0), (380.0, 150.0)), line((20.0, 158.0), (380.0, 158.0))))
    assert plan.family_stats["rivers"]["shared_cells"] > 0
    first, second = plan.chains
    assert set(second.seed_ids.tolist()) <= set(first.seed_ids.tolist())
    assert second.offset_m == pytest.approx(np.full(second.offset_m.size, 8.0))


def test_a_confluence_is_one_seed_in_three_chains() -> None:
    plan = plan_of(
        rivers(
            line((50.0, 250.0), (200.0, 150.0)),
            line((350.0, 250.0), (200.0, 150.0)),
            line((200.0, 150.0), (200.0, 20.0)),
        )
    )
    node = np.array([X0 + 200.0, Y0 + 150.0])
    frame = local_frame(DOMAIN)
    seed = int(np.argmin(np.hypot(*(plan.seeds.xy - frame.to_local(node[None, :])).T)))
    assert np.hypot(*(plan.seeds.xy[seed] - frame.to_local(node[None, :])[0])) < 1e-9
    assert all(seed in chain.seed_ids for chain in plan.chains)
    assert np.count_nonzero(plan.seeds.role == SeedRole.CHAIN) == len(
        np.unique(np.concatenate([c.seed_ids for c in plan.chains]))
    )


def test_permuted_lines_and_families_give_the_same_plan() -> None:
    face_a = line((50.0, 100.0), (350.0, 120.0))
    face_b = line((100.0, 20.0), (130.0, 280.0))
    river_a = line((20.0, 200.0), (380.0, 210.0))
    river_b = line((300.0, 290.0), (250.0, 205.4))
    lake = line((260.0, 40.0), (330.0, 40.0), (330.0, 80.0), (260.0, 40.0))
    one = plan_of(
        rivers(river_a, river_b),
        contact(face_a, face_b),
        LineFamilySpec("lakes", "face", (lake,), closed=True),
    )
    two = plan_of(
        LineFamilySpec("lakes", "face", (lake,), closed=True),
        LineFamilySpec("geology", "face", (face_b, face_a), ("l1", "l0"), ("r1", "r0")),
        rivers(river_b, river_a),
    )
    assert np.array_equal(one.seeds.xy, two.seeds.xy)
    assert np.array_equal(one.seeds.role, two.seeds.role)
    assert np.array_equal(one.faces.segment_seeds, two.faces.segment_seeds)
    assert [c.seed_ids.tolist() for c in one.chains] == [c.seed_ids.tolist() for c in two.chains]
    assert one.family_stats == two.family_stats


def test_an_acute_junction_merges_its_sector() -> None:
    angle = math.radians(15.0)
    tip = (50.0 + 300.0 * math.cos(angle), 100.0 + 300.0 * math.sin(angle))
    plan = plan_of(contact(line((50.0, 100.0), (350.0, 100.0)), line((50.0, 100.0), tip)))
    stats = plan.family_stats["geology"]
    assert stats["merged_circles"] > 0
    assert stats["conformal_length_share"] < 1.0
    assert_definition_2(plan)


def test_a_free_end_gets_a_tip_on_its_tangent() -> None:
    plan = plan_of(contact(line((100.0, 150.0), (300.0, 150.0))))
    tips = np.flatnonzero(plan.seeds.role == SeedRole.TIP)
    assert tips.size == 2
    for tip in tips.tolist():
        vertex = int(plan.seeds.vertex_id[tip])
        centre = plan.faces.vertices[vertex]
        offset = plan.seeds.xy[tip] - centre
        assert abs(offset[1]) < 1e-9
        assert abs(offset[0]) == pytest.approx(plan.faces.radius[vertex])
    assert plan.family_stats["geology"]["free_ends"] == 2.0
    assert_definition_2(plan)


def test_an_end_on_the_boundary_takes_two_ring_seeds_on_its_circle() -> None:
    plan = plan_of(contact(line((200.0, 0.0), (200.0, 200.0))))
    assert plan.family_stats["geology"]["boundary_ends"] == 1.0
    ends = np.flatnonzero((plan.seeds.role == SeedRole.BOUNDARY) & (plan.seeds.vertex_id >= 0))
    assert ends.size == 2
    vertex = int(plan.seeds.vertex_id[ends[0]])
    centre = plan.faces.vertices[vertex]
    distance = np.hypot(*(plan.seeds.xy[ends] - centre).T)
    assert distance == pytest.approx(np.full(2, plan.faces.radius[vertex]))
    bottom = local_frame(DOMAIN).to_local(np.array([[X0, Y0]]))[0, 1]
    assert plan.seeds.xy[ends, 1] == pytest.approx(np.full(2, bottom))
    assert plan.faces.conformal[vertex]
    assert_definition_2(plan)


def test_an_end_meeting_the_boundary_at_20_degrees_is_declared() -> None:
    angle = math.radians(20.0)
    plan = plan_of(
        contact(line((100.0, 0.0), (100.0 + 250.0 * math.cos(angle), 250.0 * math.sin(angle))))
    )
    stats = plan.family_stats["geology"]
    assert stats["boundary_ends"] == 0.0
    assert stats["merged_circles"] + stats["yielded_segments"] > 0
    assert_definition_2(plan)


def test_a_lake_ring_with_a_sharp_turn_keeps_definition_2() -> None:
    ring = line((100.0, 100.0), (300.0, 100.0), (260.0, 200.0), (150.0, 230.0), (100.0, 100.0))
    plan = plan_of(LineFamilySpec("lakes", "face", (ring,), closed=True))
    assert plan.family_stats["lakes"]["conformal_length_share"] == 1.0
    assert plan.faces.conformal.all()
    assert_definition_2(plan)


def test_a_sharp_vertex_shares_one_seed_between_its_two_segments() -> None:
    angle = math.radians(45.0)
    corner = (300.0, 100.0)
    back = (300.0 - 200.0 * math.cos(angle), 100.0 + 200.0 * math.sin(angle))
    plan = plan_of(contact(line((100.0, 100.0), corner, back)))
    faces = plan.faces
    frame = local_frame(DOMAIN)
    local = frame.to_local(np.array([[X0 + corner[0], Y0 + corner[1]]]))[0]
    vertex = int(np.argmin(np.hypot(*(faces.vertices - local).T)))
    incident = np.flatnonzero((faces.segment_nodes == vertex).any(axis=1))
    shared = np.intersect1d(faces.segment_seeds[incident[0]], faces.segment_seeds[incident[1]])
    assert shared.size == 1 and shared[0] >= 0
    nodes = np.unique(faces.segment_nodes[incident])
    distance = np.hypot(*(faces.vertices[nodes] - plan.seeds.xy[shared[0]]).T)
    assert distance == pytest.approx(faces.radius[nodes], rel=1e-9)
    assert faces.conformal[vertex]
    assert_definition_2(plan)


def test_a_face_line_on_the_domain_boundary_is_left_to_the_boundary() -> None:
    ring = LineString(DOMAIN.exterior.coords)
    plan = plan_of(
        LineFamilySpec("watershed_boundary", "face", (ring,), closed=True), resample=False
    )
    assert plan.faces.segment_nodes.shape == (0, 2)
    assert any("watershed_boundary" in note for note in plan.notes)


def test_a_contact_parallel_to_a_river_yields_to_it() -> None:
    plan = plan_of(
        rivers(line((20.0, 150.0), (380.0, 150.0))),
        contact(line((100.0, 156.0), (300.0, 156.0))),
    )
    assert plan.family_stats["geology"]["yielded_segments"] > 0
    (chain,) = plan.chains
    assert np.all(chain.offset_m == 0.0)
    assert np.all(plan.seeds.role[chain.seed_ids] == SeedRole.CHAIN)


def test_constraint_seeds_lie_in_the_domain() -> None:
    plan = crossing_plan()
    domain = local_frame(DOMAIN).to_local(DOMAIN)
    assert shapely.intersects_xy(domain, plan.seeds.xy[:, 0], plan.seeds.xy[:, 1]).all()


def test_gate_inputs_follow_the_plan() -> None:
    plan = crossing_plan()
    balls = plan.berge_balls()
    assert balls.vertex_id.tolist() == np.flatnonzero(plan.faces.conformal).tolist()
    faces = plan.mirror_faces()
    assert len(faces.plus) == plan.family_stats["geology"]["mirror_pairs"]
    start, end = plan.chain_segments()
    assert len(start) == len(end) == plan.chains[0].seed_ids.size - 1
    extras = plan.seed_extras()
    assert sum(extras.values()) == plan.seeds.n


def test_a_request_without_size_field_is_refused() -> None:
    field = size_field(DOMAIN, 5.0, H)
    request = MeshRequest(domain=DOMAIN, crs_wkt=WKT, grid=field.grid, nominal_size_m=H)
    frame = local_frame(DOMAIN)
    with pytest.raises(MeshRequestError, match="size field"):
        place_constraints(request, frame, SizeSampler(field, frame))


def barriers(*lines: LineString) -> LineFamilySpec:
    return LineFamilySpec("barriers", "face", lines)


def test_a_contact_beside_a_barrier_yields_to_it() -> None:
    plan = plan_of(
        contact(line((100.0, 156.0), (300.0, 156.0))),
        barriers(line((100.0, 150.0), (300.0, 150.0))),
    )

    assert plan.family_stats["barriers"]["conformal_length_share"] == 1.0
    assert plan.family_stats["geology"]["yielded_segments"] > 0


def test_a_barrier_on_a_lake_ring_leaves_the_stretch_to_it_and_shares_its_faces() -> None:
    ring = shapely.get_coordinates(
        resample_families(
            (
                LineFamilySpec(
                    "lakes",
                    "face",
                    (line((100, 100), (300, 100), (300, 200), (100, 200), (100, 100)),),
                    closed=True,
                ),
            ),
            domain=DOMAIN,
            size_field=size_field(DOMAIN, 5.0, H),
        )
        .families[0]
        .lines[0]
    )
    on_side = ring[np.isclose(ring[:, 0], X0 + 300.0)]
    on_side = on_side[np.argsort(on_side[:, 1])]
    wings = [(X0 + x, Y0 + y) for x, y in ((360.0, 100.0), (340.0, 100.0), (320.0, 100.0))]
    wall = LineString([*wings, *map(tuple, on_side), *[(x, y + 100.0) for x, y in wings[::-1]]])
    lake = LineFamilySpec("lakes", "face", (LineString(ring),), closed=True)
    plan = plan_of(lake, barriers(wall), resample=False)
    faces = plan.faces
    pairs = [tuple(sorted(pair)) for pair in faces.segment_nodes.tolist()]
    shared = faces.alias_family == plan.family_names.index("barriers")

    assert len(pairs) == len(set(pairs))
    assert np.count_nonzero(shared) == len(on_side) - 1
    assert np.all(faces.segment_family[faces.alias_segment] == plan.family_names.index("lakes"))
    assert plan.family_stats["barriers"]["conformal_length_share"] == 1.0
    assert_definition_2(plan)


@pytest.mark.parametrize("angle", [60.0, 20.0])
def test_a_river_never_makes_a_barrier_yield(angle: float) -> None:
    tangent = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    centre = np.array([200.0, 150.0])
    plan = plan_of(
        rivers(line((20.0, 150.0), (380.0, 150.0))),
        barriers(line(tuple(centre - 140.0 * tangent), tuple(centre + 140.0 * tangent))),
    )
    (chain,) = plan.chains
    barrier = plan.family_names.index("barriers")
    stats = plan.family_stats["barriers"]

    assert stats["yielded_segments"] == 0.0
    assert stats["conformal_length_share"] == 1.0
    assert plan.family_stats["rivers"]["crossings"] == 1.0
    assert np.any(plan.seeds.family[chain.seed_ids] == barrier)
    assert_definition_2(plan)
