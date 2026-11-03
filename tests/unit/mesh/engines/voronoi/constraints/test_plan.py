"""Placement of the constraint seeds: chains, mirror pairs, crossings, the boundary and the conflicts.

A field situation is the plan of ``place_constraints`` on a catchment of 400 m by
300 m meshed at 20 m, its lines resampled as the planner does. The table
``SITUATIONS`` runs every situation through the invariants a plan keeps whatever
the conflict rules decided. The named tests then check one rule each, on the
situation that triggers it.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable

import numpy as np
import pytest
import shapely
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.engines.voronoi.checks import mirror_face_runs
from hydromodpy.spatial.mesh.engines.voronoi.constraints.conflicts import CONFLICT_SHARE
from hydromodpy.spatial.mesh.engines.voronoi.constraints.lines import FACE_PRIORITY
from hydromodpy.spatial.mesh.engines.voronoi.constraints.plan import (
    ConstraintPlan,
    place_constraints,
)
from hydromodpy.spatial.mesh.engines.voronoi.constraints.rivers import CROSSING_ABSORB_SHARE
from hydromodpy.spatial.mesh.engines.voronoi.constraints.state import CIRCLE_SHRINK, SeedRole
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import constraint_disks
from hydromodpy.spatial.mesh.engines.voronoi.local_coords import SizeSampler, local_frame
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec, MeshRequest, SizeField
from hydromodpy.spatial.mesh.resample import resample_families
from tests._helpers import reservoir_dam
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    grid_over,
    mesh_request,
    uniform_size_field,
    voronoi_lake_mesh,
)

X0, Y0 = L93_ORIGIN
H = 20.0
PIXEL = 5.0
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)


def at(x: float, y: float) -> tuple[float, float]:
    """A point given in meters from the south-west corner of ``DOMAIN``."""
    return (X0 + x, Y0 + y)


def line(*points: tuple[float, float]) -> LineString:
    """A line given in meters from the domain corner."""
    return LineString([at(*point) for point in points])


def ring(*points: tuple[float, float]) -> LineString:
    """A closed line through *points*, given in meters from the domain corner."""
    return line(*points, points[0])


def polar(origin: tuple[float, float], length: float, angle_deg: float) -> tuple[float, float]:
    """The point *length* meters from *origin* at *angle_deg* counter-clockwise from east."""
    a = math.radians(angle_deg)
    return (origin[0] + length * math.cos(a), origin[1] + length * math.sin(a))


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


def lakes(*rings: LineString) -> LineFamilySpec:
    return LineFamilySpec("lakes", "face", rings, closed=True)


def barriers(*lines: LineString) -> LineFamilySpec:
    return LineFamilySpec(BARRIER_FAMILY, "face", lines)


def with_holes(*holes: Polygon) -> Polygon:
    """``DOMAIN`` with *holes*, given in world coordinates."""
    return Polygon(DOMAIN.exterior.coords, [hole.exterior.coords for hole in holes])


def banded_field(west: float, east: float, fine: float, coarse: float) -> SizeField:
    """A field of *coarse* meters with a north-south band of *fine* meters between *west* and *east*."""
    grid = grid_over(DOMAIN, PIXEL)
    x = grid.xmin + (np.arange(grid.ncol) + 0.5) * grid.dx - X0
    row = np.where((x >= west) & (x < east), fine, coarse)
    return SizeField(np.broadcast_to(row, (grid.nrow, grid.ncol)).copy(), grid)


def request_of(
    *families: LineFamilySpec,
    domain: Polygon = DOMAIN,
    field: SizeField | None = None,
    pixel: float = PIXEL,
    resample: bool = True,
) -> MeshRequest:
    """The request of the families, resampled on the field like the planner does."""
    field = uniform_size_field(grid_over(DOMAIN, pixel), H) if field is None else field
    if resample:
        families = resample_families(families, domain=domain, size_field=field).families
    return mesh_request(
        field.grid,
        domain=domain,
        nominal_size_m=float(field.values.max()),
        lines=families,
        size_field=field,
    )


def plan_of(*families: LineFamilySpec, **request: object) -> ConstraintPlan:
    """The constraint plan of the families, resampled at ``H`` like the planner does."""
    built = request_of(*families, **request)
    frame = local_frame(built.domain)
    return place_constraints(built, frame, SizeSampler(built.size_field, frame))


def local(*points: tuple[float, float]) -> np.ndarray:
    """Points given from the domain corner, in the local frame of ``DOMAIN`` and its subsets."""
    return local_frame(DOMAIN).to_local(np.asarray([at(*point) for point in points]))


def assert_definition_2(plan: ConstraintPlan) -> None:
    """No constraint seed lies inside the ball of a conformal vertex."""
    faces = plan.faces
    if not faces.conformal.any():
        return
    center, radius = faces.vertices[faces.conformal], faces.radius[faces.conformal]
    found = cKDTree(plan.seeds.xy).query_ball_point(center, radius * (1 - CIRCLE_SHRINK))
    assert all(not hits for hits in found)


def assert_no_two_seeds_closer_than_the_conflict_share(plan: ConstraintPlan) -> None:
    """Of two constraint seeds closer than 0.05 local cell, one went."""
    xy, size = plan.seeds.xy, plan.seeds.radius
    pairs = cKDTree(xy).query_pairs(CONFLICT_SHARE * float(size.max()), output_type="ndarray")
    gap = np.hypot(*(xy[pairs[:, 0]] - xy[pairs[:, 1]]).T)
    assert np.all(gap >= CONFLICT_SHARE * np.minimum(size[pairs[:, 0]], size[pairs[:, 1]]))


def assert_chain_links_are_clear(plan: ConstraintPlan, domain: Polygon) -> None:
    """The disk on each chain link holds no other seed, except one across the domain boundary."""
    cover = local_frame(DOMAIN).to_local(domain).buffer(1.0e-6)
    xy = plan.seeds.xy
    tree = cKDTree(xy)
    for chain in plan.chains:
        ids = chain.cell_ids
        for a, b in zip(ids[:-1].tolist(), ids[1:].tolist(), strict=True):
            middle, reach = 0.5 * (xy[a] + xy[b]), 0.5 * np.hypot(*(xy[b] - xy[a]))
            for seed in tree.query_ball_point(middle, reach * (1.0 - 1.0e-9)):
                if seed in (a, b):
                    continue
                chords = shapely.linestrings([[xy[a], xy[seed]], [xy[b], xy[seed]]])
                assert not shapely.covers(cover, chords).all(), f"seed {seed} in link {a}-{b}"


def assert_seeds_lie_in_the_domain(plan: ConstraintPlan, domain: Polygon) -> None:
    inside = local_frame(DOMAIN).to_local(domain).buffer(1.0e-6)
    assert shapely.intersects_xy(inside, plan.seeds.xy[:, 0], plan.seeds.xy[:, 1]).all()


def assert_the_shore_stretch_is_fed_once(plan: ConstraintPlan) -> None:
    """Each segment is fed once, and the wall stretch on the shore is a lake segment the wall shares."""
    faces = plan.faces
    pairs = [tuple(sorted(pair)) for pair in faces.segment_nodes.tolist()]
    assert len(pairs) == len(set(pairs))
    assert np.count_nonzero(faces.shared_family == plan.family_names.index(BARRIER_FAMILY)) >= 5
    assert np.all(faces.segment_family[faces.shared_segment] == plan.family_names.index("lakes"))
    assert plan.family_stats[BARRIER_FAMILY]["yielded_segments"] == 0.0


def slot_domain(width: float) -> Polygon:
    """``DOMAIN`` cut by a slot *width* meters wide from its north side down to 80 m."""
    west, east = 200.0 - 0.5 * width, 200.0 + 0.5 * width
    return Polygon(
        [at(0, 0), at(400, 0), at(400, 300), at(east, 300), at(east, 80), at(west, 80)]
        + [at(west, 300), at(0, 300)]
    )


def lake_tip(half_angle_deg: float) -> LineString:
    """A lake shaped as a wedge whose tip points east at (330, 150)."""
    tip = (330.0, 150.0)
    return ring(
        tip, polar(tip, 250.0, 180.0 - half_angle_deg), polar(tip, 250.0, 180.0 + half_angle_deg)
    )


def crossing_plan() -> ConstraintPlan:
    return situation("a river crossing a contact at 60 degrees")[0]


SITUATIONS: dict[str, Callable[[], tuple[tuple[LineFamilySpec, ...], dict[str, object]]]] = {
    "a river crossing a contact at 60 degrees": lambda: (
        (
            rivers(line((20, 150), (380, 150))),
            contact(line(polar((200, 150), 160, 240), polar((200, 150), 160, 60))),
        ),
        {},
    ),
    "two contacts leaving one point at 15 degrees": lambda: (
        (
            contact(
                line((50.0, 100.0), (350.0, 100.0)),
                line((50.0, 100.0), polar((50.0, 100.0), 300.0, 15.0)),
            ),
        ),
        {},
    ),
    "a river crossing a lake twice": lambda: (
        (
            rivers(line((20, 150), (380, 150))),
            lakes(ring((150, 100), (250, 100), (250, 200), (150, 200))),
        ),
        {},
    ),
    "a river cutting the narrow tip of a lake": lambda: (
        (rivers(line((310, 20), (310, 280))), lakes(lake_tip(20.0))),
        {},
    ),
    "a river ending in a pond smaller than a cell": lambda: (
        (
            rivers(line((20, 150), (200, 150))),
            lakes(ring((192, 142), (208, 142), (208, 158), (192, 158))),
        ),
        {},
    ),
    "a pond smaller than a cell on a river": lambda: (
        (rivers(line((20, 150), (380, 150))), lakes(ring((200, 144), (206, 156), (194, 156)))),
        {},
    ),
    "two lakes on either side of a sill": lambda: (
        (
            lakes(
                ring((100, 100), (200, 100), (200, 200), (100, 200)),
                ring((200, 100), (300, 100), (300, 200), (200, 200)),
            ),
        ),
        {},
    ),
    "a lake cut open by the catchment edge beside a river": lambda: (
        (
            rivers(line((20, 92), (380, 92))),
            lakes(ring((0, 100), (150, 100), (150, 200), (0, 200))),
        ),
        {},
    ),
    "two thalwegs on both sides of a slot of the catchment": lambda: (
        (rivers(line((196, 290), (196, 100), (150, 20)), line((204, 290), (204, 100), (250, 20))),),
        {"domain": slot_domain(2.0)},
    ),
    "two thalwegs meeting below a slot of the catchment": lambda: (
        (rivers(line((196, 290), (196, 40)), line((204, 290), (204, 60))),),
        {"domain": slot_domain(2.0)},
    ),
    "a thalweg between two others ten metres apart": lambda: (
        (
            rivers(
                line((20, 150), (380, 150)),
                line((20, 160.5), (380, 160.5)),
                line((40, 155), (360, 155)),
            ),
        ),
        {},
    ),
    "three thalwegs four metres apart": lambda: (
        (
            rivers(
                line((20, 150), (380, 150)),
                line((20, 154), (380, 154)),
                line((20, 158), (380, 158)),
            ),
        ),
        {},
    ),
    "a tributary stub beside the main river": lambda: (
        (rivers(line((20, 150), (380, 150)), line((200, 156), (204, 152))),),
        {},
    ),
    "a river rising five metres before a contact": lambda: (
        (rivers(line((195, 150), (380, 150))), contact(line((200, 20), (200, 280)))),
        {},
    ),
    "a confluence two metres beside a contact": lambda: (
        (
            rivers(line((20, 150), (380, 150)), line((202, 280), (202, 150))),
            contact(line((200, 20), (200, 280))),
        ),
        {},
    ),
    "two contacts four metres apart across a river": lambda: (
        (
            rivers(line((20, 150), (380, 150))),
            contact(line((200, 20), (200, 280)), line((204, 20), (204, 280))),
        ),
        {},
    ),
    "a crossing beside a barrier": lambda: (
        (
            rivers(line((20, 150), (380, 150))),
            contact(line((200, 20), (200, 280))),
            barriers(line((212, 20), (212, 280))),
        ),
        {},
    ),
    "a contact junction thirty centimetres above a river": lambda: (
        (
            rivers(line((20, 150), (380, 150))),
            contact(line((200, 150.3), (200, 280))),
            contact(line((60, 151), (200, 150.3)), name="faults"),
        ),
        {},
    ),
    "three contacts meeting within half a metre": lambda: (
        (
            contact(
                line((60, 150), (340, 150)),
                line((200, 150.3), (200, 280)),
                line((200.3, 150.3), (210, 20)),
            ),
        ),
        {},
    ),
    "a contact stopping eight metres short of another": lambda: (
        (contact(line((60, 150), (340, 150)), line((200, 280), (200, 158))),),
        {},
    ),
    "a contact folding back at 20 degrees": lambda: (
        (contact(line((50, 150), (200, 150), polar((200, 150), 150, 160))),),
        {},
    ),
    "a contact digitised down to a river and back": lambda: (
        (rivers(line((20, 150), (380, 150))), contact(line((100, 280), (200, 150), (100, 280)))),
        {},
    ),
    "a contact through the fine band of a river corridor": lambda: (
        (contact(line((40, 150), (360, 150))),),
        {"field": banded_field(190.0, 210.0, 10.0, 25.0)},
    ),
    "a contact running along the catchment edge": lambda: (
        (contact(line((50, 0), (150, 0), (150, 200), (300, 250))),),
        {},
    ),
    "a contact ending on the edge beside a corner": lambda: (
        (contact(line((5, 0), (55, 250))),),
        {},
    ),
    "a river reaching the edge beside the end of a contact": lambda: (
        (rivers(line((230, 150), (184, 0))), contact(line((200, 0), (300, 250)))),
        {},
    ),
    "a contact ending on a hole narrower than its end circle": lambda: (
        (contact(line((100, 100), (200, 153))),),
        {"domain": with_holes(box(*at(200, 150), *at(206, 156)))},
    ),
    "a contact ending on a hole as wide as its end circle": lambda: (
        (contact(line((100, 100), (205, 150))),),
        {"domain": with_holes(box(*at(200, 150), *at(210, 160)))},
    ),
    "a contact ending on a small round hole": lambda: (
        (contact(line((100, 100), (193, 150))),),
        {"domain": with_holes(Point(at(200, 150)).buffer(7.0, 16)), "pixel": 10.0},
    ),
    "a contact from the edge to a round hole": lambda: (
        (contact(line((200, 0), (200, 110))),),
        {"domain": with_holes(Point(at(200, 150)).buffer(40.0, 16))},
    ),
    "a round catchment": lambda: (
        (contact(line((100, 150), (300, 150))),),
        {"domain": Point(at(200, 150)).buffer(140.0, 32)},
    ),
    "a river leaving at a corner": lambda: ((rivers(line((200, 150), (400, 300))),), {}),
}


@functools.cache
def situation(name: str) -> tuple[ConstraintPlan, Polygon]:
    families, options = SITUATIONS[name]()
    return plan_of(*families, **options), options.get("domain", DOMAIN)


@pytest.mark.parametrize("name", SITUATIONS)
def test_no_seed_lies_in_the_ball_of_a_conformal_vertex(name: str) -> None:
    plan, _ = situation(name)
    assert_definition_2(plan)


@pytest.mark.parametrize("name", SITUATIONS)
def test_no_two_seeds_lie_closer_than_the_conflict_share(name: str) -> None:
    plan, _ = situation(name)
    assert_no_two_seeds_closer_than_the_conflict_share(plan)


@pytest.mark.parametrize("name", SITUATIONS)
def test_every_chain_link_keeps_its_disk_clear(name: str) -> None:
    plan, domain = situation(name)
    assert_chain_links_are_clear(plan, domain)


@pytest.mark.parametrize("name", SITUATIONS)
def test_the_constraint_seeds_lie_in_the_domain(name: str) -> None:
    plan, domain = situation(name)
    assert_seeds_lie_in_the_domain(plan, domain)


POINTS = st.tuples(
    st.integers(40, 760).map(lambda x: x / 2.0), st.integers(40, 560).map(lambda y: y / 2.0)
)
"""A point of the catchment on a half-meter grid, 20 m at least from its edge."""

POLYLINES = st.lists(POINTS, min_size=2, max_size=4, unique=True)


@settings(derandomize=True, deadline=None, max_examples=50)
@given(
    river=st.one_of(st.none(), POLYLINES),
    faces=st.lists(POLYLINES, min_size=1, max_size=2),
    family=st.sampled_from(["geology", BARRIER_FAMILY]),
)
def test_random_lines_keep_the_invariants_of_a_plan(
    river: list[tuple[float, float]] | None, faces: list[list[tuple[float, float]]], family: str
) -> None:
    for points in [*faces, *([river] if river else [])]:
        assume(LineString(points).length > 1.0)
    families = [contact(*(line(*points) for points in faces), name=family)]
    if river:
        families.append(rivers(line(*river)))
    plan = plan_of(*families)
    assert_definition_2(plan)
    assert_no_two_seeds_closer_than_the_conflict_share(plan)
    assert_chain_links_are_clear(plan, DOMAIN)
    assert_seeds_lie_in_the_domain(plan, DOMAIN)


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
    mirror = np.flatnonzero(plan.seeds.role[chain.cell_ids] == SeedRole.MIRROR)
    assert mirror.tolist() == [mirror[0], mirror[0] + 1]
    assert plan.family_stats["rivers"]["crossings"] == 1.0
    faces = plan.faces
    segment = int(plan.seeds.pair_id[chain.cell_ids[mirror[0]]])
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
    upstream = plan.seeds.xy[chain.cell_ids[mirror[0] - 1]] - foot
    first = plan.seeds.xy[chain.cell_ids[mirror[0]]] - foot
    side = unit[0] * first[1] - unit[1] * first[0]
    assert np.sign(side) == np.sign(unit[0] * upstream[1] - unit[1] * upstream[0])
    assert_definition_2(plan)


def test_thalwegs_closer_than_half_a_cell_share_their_cells() -> None:
    plan = plan_of(rivers(line((20.0, 150.0), (380.0, 150.0)), line((20.0, 158.0), (380.0, 158.0))))
    assert plan.family_stats["rivers"]["shared_cells"] > 0
    first, second = plan.chains
    assert set(second.cell_ids.tolist()) <= set(first.cell_ids.tolist())
    assert second.offset_m == pytest.approx(np.full(second.offset_m.size, 8.0))


def test_a_thalweg_between_two_others_takes_the_cells_of_the_nearer() -> None:
    plan, _ = situation("a thalweg between two others ten metres apart")
    first, second, middle = plan.chains
    assert not set(first.cell_ids.tolist()) & set(second.cell_ids.tolist())
    assert set(middle.cell_ids.tolist()) <= set(first.cell_ids.tolist())
    assert middle.offset_m == pytest.approx(np.full(middle.offset_m.size, 5.0))


def test_of_three_close_thalwegs_the_later_ones_share_the_cells_of_the_first() -> None:
    plan, _ = situation("three thalwegs four metres apart")
    first, second, third = plan.chains
    assert second.cell_ids.tolist() == first.cell_ids.tolist() == third.cell_ids.tolist()
    assert second.offset_m == pytest.approx(np.full(second.offset_m.size, 4.0))
    assert third.offset_m == pytest.approx(np.full(third.offset_m.size, 8.0))


def test_thalwegs_on_both_sides_of_a_slot_keep_their_own_cells() -> None:
    plan, _ = situation("two thalwegs on both sides of a slot of the catchment")
    west, east = plan.chains
    assert plan.family_stats["rivers"]["shared_cells"] == 0.0
    assert not set(west.cell_ids.tolist()) & set(east.cell_ids.tolist())
    assert np.all(plan.seeds.role[np.concatenate([west.cell_ids, east.cell_ids])] == SeedRole.CHAIN)


def test_thalwegs_meeting_below_a_slot_share_cells_only_below_it() -> None:
    plan, _ = situation("two thalwegs meeting below a slot of the catchment")
    west, east = plan.chains
    shared = np.intersect1d(west.cell_ids, east.cell_ids)
    bottom = local((200.0, 80.0))[0, 1]
    assert plan.family_stats["rivers"]["shared_cells"] == shared.size > 0
    assert np.all(plan.seeds.xy[shared, 1] < bottom)


def test_a_tributary_stub_within_half_a_cell_is_one_cell_of_the_main_river() -> None:
    plan, _ = situation("a tributary stub beside the main river")
    main, stub = plan.chains
    assert stub.cell_ids.size == 1
    assert stub.cell_ids[0] in main.cell_ids
    assert plan.family_stats["rivers"]["shared_cells"] == 2.0


def test_a_confluence_is_one_seed_in_three_chains() -> None:
    plan = plan_of(
        rivers(
            line((50.0, 250.0), (200.0, 150.0)),
            line((350.0, 250.0), (200.0, 150.0)),
            line((200.0, 150.0), (200.0, 20.0)),
        )
    )
    node = local((200.0, 150.0))[0]
    seed = int(np.argmin(np.hypot(*(plan.seeds.xy - node).T)))
    assert np.hypot(*(plan.seeds.xy[seed] - node)) < 1e-9
    assert all(seed in chain.cell_ids for chain in plan.chains)
    assert np.count_nonzero(plan.seeds.role == SeedRole.CHAIN) == len(
        np.unique(np.concatenate([c.cell_ids for c in plan.chains]))
    )


def test_the_chains_of_a_plan_are_numbered_by_rank() -> None:
    plan = plan_of(
        rivers(
            line((50.0, 250.0), (200.0, 150.0)),
            line((350.0, 250.0), (200.0, 150.0)),
            line((200.0, 150.0), (200.0, 20.0)),
        )
    )
    assert [chain.chain_id for chain in plan.chains] == [0, 1, 2]
    assert {chain.family for chain in plan.chains} == {"rivers"}


def test_permuted_lines_and_families_give_the_same_plan() -> None:
    face_a = line((50.0, 100.0), (350.0, 120.0))
    face_b = line((100.0, 20.0), (130.0, 280.0))
    river_a = line((20.0, 200.0), (380.0, 210.0))
    river_b = line((300.0, 290.0), (250.0, 205.4))
    lake = line((260.0, 40.0), (330.0, 40.0), (330.0, 80.0), (260.0, 40.0))
    one = plan_of(rivers(river_a, river_b), contact(face_a, face_b), lakes(lake))
    two = plan_of(
        lakes(lake),
        LineFamilySpec("geology", "face", (face_b, face_a), ("l1", "l0"), ("r1", "r0")),
        rivers(river_b, river_a),
    )
    assert np.array_equal(one.seeds.xy, two.seeds.xy)
    assert np.array_equal(one.seeds.role, two.seeds.role)
    assert np.array_equal(one.faces.segment_seeds, two.faces.segment_seeds)
    assert [c.cell_ids.tolist() for c in one.chains] == [c.cell_ids.tolist() for c in two.chains]
    assert one.family_stats == two.family_stats


def test_a_face_family_without_a_rank_comes_after_the_ranked_ones_by_name() -> None:
    plan = plan_of(
        contact(line((50, 50), (350, 60)), name="faults"),
        contact(line((50, 120), (350, 130)), name="dykes"),
        contact(line((60, 250), (340, 240))),
        rivers(line((20, 180), (380, 190))),
    )
    assert not {"dykes", "faults"} & set(FACE_PRIORITY)
    assert plan.family_names == ("rivers", "geology", "dykes", "faults")


@pytest.mark.parametrize(
    "name", ["two contacts leaving one point at 15 degrees", "a contact folding back at 20 degrees"]
)
def test_an_acute_sector_merges_its_circles(name: str) -> None:
    plan, _ = situation(name)
    stats = plan.family_stats["geology"]
    assert stats["merged_circles"] > 0
    assert stats["conformal_length_share"] < 1.0
    assert_definition_2(plan)


@pytest.mark.parametrize("vertical_end", [150.0, 20.0], ids=["t", "x"])
def test_a_t_or_x_junction_of_contacts_keeps_definition_2_at_its_node(vertical_end: float) -> None:
    plan = plan_of(
        contact(line((50.0, 150.0), (350.0, 150.0)), line((200.0, 280.0), (200.0, vertical_end)))
    )
    vertex = int(np.argmin(np.hypot(*(plan.faces.vertices - local((200.0, 150.0))[0]).T)))
    assert plan.family_stats["geology"]["conformal_length_share"] == 1.0
    assert plan.faces.conformal[vertex]
    assert_definition_2(plan)


def test_a_free_end_gets_a_tip_on_its_tangent() -> None:
    plan = plan_of(contact(line((100.0, 150.0), (300.0, 150.0))))
    tips = np.flatnonzero(plan.seeds.role == SeedRole.FREE_END)
    assert tips.size == 2
    for tip in tips.tolist():
        vertex = int(plan.seeds.vertex_id[tip])
        centre = plan.faces.vertices[vertex]
        offset = plan.seeds.xy[tip] - centre
        assert abs(offset[1]) < 1e-9
        assert abs(offset[0]) == pytest.approx(plan.faces.radius[vertex])
    assert plan.family_stats["geology"]["free_ends"] == 2.0
    assert_definition_2(plan)


def test_a_contact_shorter_than_a_cell_is_one_pair_and_two_tips() -> None:
    plan = plan_of(contact(line((100.0, 100.0), (110.0, 105.0))))
    stats = plan.family_stats["geology"]
    assert len(plan.faces.segment_nodes) == 1
    assert stats["mirror_pairs"] == 1.0
    assert stats["free_ends"] == 2.0
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
    bottom = local((0.0, 0.0))[0, 1]
    assert plan.seeds.xy[ends, 1] == pytest.approx(np.full(2, bottom))
    assert plan.faces.conformal[vertex]
    assert_definition_2(plan)


def test_an_end_on_the_outer_ring_takes_its_seeds_there_and_none_on_a_hole() -> None:
    hole = box(*at(250, 100), *at(330, 200))
    plan = plan_of(contact(line((100.0, 0.0), (120.0, 250.0))), domain=with_holes(hole))
    ends = np.flatnonzero((plan.seeds.role == SeedRole.BOUNDARY) & (plan.seeds.vertex_id >= 0))
    assert plan.family_stats["geology"]["boundary_ends"] == 1.0
    assert plan.seeds.xy[ends, 1] == pytest.approx(np.full(2, local((0.0, 0.0))[0, 1]))


@pytest.mark.parametrize("angle", [20.0, 25.0])
def test_an_end_meeting_the_boundary_at_a_low_angle_is_declared(angle: float) -> None:
    plan = plan_of(contact(line((100.0, 0.0), polar((100.0, 0.0), 250.0, angle))))
    stats = plan.family_stats["geology"]
    assert stats["boundary_ends"] == 0.0
    assert stats["merged_circles"] + stats["yielded_segments"] > 0
    assert_definition_2(plan)


@pytest.mark.parametrize(
    "name",
    [
        "a contact ending on the edge beside a corner",
        "a contact ending on a hole narrower than its end circle",
        "a contact ending on a hole as wide as its end circle",
    ],
)
def test_an_end_whose_circle_has_no_room_on_the_ring_merges_its_last_segment(name: str) -> None:
    plan, _ = situation(name)
    stats = plan.family_stats["geology"]
    assert stats["boundary_ends"] == 0.0
    assert stats["merged_circles"] == 1.0


def test_two_ends_closer_than_their_circles_on_the_edge_leave_the_ring_to_the_first() -> None:
    plan = plan_of(contact(line((200.0, 0.0), (150.0, 250.0)), line((210.0, 0.0), (300.0, 250.0))))
    stats = plan.family_stats["geology"]
    assert stats["boundary_ends"] == 1.0
    assert stats["merged_circles"] == 1.0
    assert_definition_2(plan)


def test_a_river_reaching_the_edge_beside_a_contact_end_takes_its_ring_seed() -> None:
    plan, _ = situation("a river reaching the edge beside the end of a contact")
    end = local((200.0, 0.0))[0]
    vertex = int(np.argmin(np.hypot(*(plan.faces.vertices - end).T)))
    stats = plan.family_stats["geology"]
    assert stats["boundary_ends"] == 0.0
    assert stats["conformal_length_share"] == 1.0
    assert not plan.faces.conformal[vertex]
    assert np.count_nonzero(plan.seeds.vertex_id == vertex) == 1


def test_a_lake_ring_with_a_sharp_turn_keeps_definition_2() -> None:
    plan = plan_of(lakes(ring((100.0, 100.0), (300.0, 100.0), (260.0, 200.0), (150.0, 230.0))))
    assert plan.family_stats["lakes"]["conformal_length_share"] == 1.0
    assert plan.faces.conformal.all()
    assert_definition_2(plan)


def test_a_sharp_vertex_shares_one_seed_between_its_two_segments() -> None:
    corner = (300.0, 100.0)
    plan = plan_of(contact(line((100.0, 100.0), corner, polar(corner, 200.0, 135.0))))
    faces = plan.faces
    vertex = int(np.argmin(np.hypot(*(faces.vertices - local(corner)[0]).T)))
    incident = np.flatnonzero((faces.segment_nodes == vertex).any(axis=1))
    shared = np.intersect1d(faces.segment_seeds[incident[0]], faces.segment_seeds[incident[1]])
    assert shared.size == 1 and shared[0] >= 0
    nodes = np.unique(faces.segment_nodes[incident])
    distance = np.hypot(*(faces.vertices[nodes] - plan.seeds.xy[shared[0]]).T)
    assert distance == pytest.approx(faces.radius[nodes], rel=1e-9)
    assert faces.conformal[vertex]
    assert_definition_2(plan)


def test_a_straight_vertex_between_two_short_segments_makes_one_face_of_both() -> None:
    plan, _ = situation("a contact through the fine band of a river corridor")
    faces = plan.faces
    pairs = [tuple(pair) for pair in faces.segment_seeds[faces.segment_conformal].tolist()]
    (run,) = [pair for pair in set(pairs) if pairs.count(pair) == 2]
    first, second = np.flatnonzero((faces.segment_seeds == run).all(axis=1))
    runs = mirror_face_runs(faces)

    assert faces.segment_nodes[first, 1] == faces.segment_nodes[second, 0]
    assert len(runs) == len(pairs) - 1
    (face,) = np.flatnonzero(runs[:, 0] == first)
    assert runs[face].tolist() == [first, second]


def test_the_face_of_a_shared_pair_run_passes_the_gates() -> None:
    families, options = SITUATIONS["a contact through the fine band of a river corridor"]()
    cell_mesh = VoronoiMeshEngine().build(request_of(*families, **options))
    assert cell_mesh.qa.families["geology"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)


def test_a_face_line_on_the_domain_boundary_is_left_to_the_boundary() -> None:
    plan = plan_of(
        LineFamilySpec(
            "watershed_boundary", "face", (LineString(DOMAIN.exterior.coords),), closed=True
        ),
        resample=False,
    )
    assert plan.faces.segment_nodes.shape == (0, 2)
    assert any("watershed_boundary" in note for note in plan.notes)


def test_a_contact_running_along_the_edge_leaves_that_stretch_to_the_boundary() -> None:
    plan, _ = situation("a contact running along the catchment edge")
    (family,), _ = SITUATIONS["a contact running along the catchment edge"]()
    (resampled,) = request_of(family).lines[0].lines
    faces = plan.faces
    start, stop = (
        faces.vertices[faces.segment_nodes[:, 0]],
        faces.vertices[faces.segment_nodes[:, 1]],
    )
    edge = local_frame(DOMAIN).to_local(DOMAIN).boundary

    assert shapely.distance(shapely.points(0.5 * (start + stop)), edge).min() > 1.0
    assert np.hypot(*(stop - start).T).sum() == pytest.approx(resampled.length - 100.0, rel=1e-9)
    assert plan.family_stats["geology"]["boundary_ends"] == 1.0
    assert any("geology" in note for note in plan.notes)


def test_a_contact_parallel_to_a_river_yields_to_it() -> None:
    plan = plan_of(
        rivers(line((20.0, 150.0), (380.0, 150.0))),
        contact(line((100.0, 156.0), (300.0, 156.0))),
    )
    assert plan.family_stats["geology"]["yielded_segments"] > 0
    (chain,) = plan.chains
    assert np.all(chain.offset_m == 0.0)
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_a_contact_ending_on_a_river_is_not_opened_and_its_end_yields() -> None:
    plan = plan_of(rivers(line((20, 150), (380, 150))), contact(line((200, 150), (210, 280))))
    (chain,) = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert plan.family_stats["geology"]["yielded_segments"] == 1.0
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_a_river_touching_a_contact_without_crossing_it_is_not_opened() -> None:
    plan = plan_of(
        rivers(line((20, 100), (200, 150), (380, 100))), contact(line((20, 150), (380, 150)))
    )
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert plan.family_stats["geology"]["yielded_segments"] > 0


def test_a_crossing_closer_than_half_a_cell_to_the_edge_is_not_opened() -> None:
    plan = plan_of(rivers(line((5, 290), (5, 10))), contact(line((0, 150), (300, 150))))
    (chain,) = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_a_contact_digitised_down_to_a_river_and_back_is_not_opened() -> None:
    plan, _ = situation("a contact digitised down to a river and back")
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert plan.family_stats["geology"]["mirror_pairs"] == 0.0


def test_a_crossing_absorbs_the_contact_vertices_within_its_reach() -> None:
    families = (rivers(line((20, 150), (380, 150))), contact(line((200, 98), (200, 202))))
    plan = plan_of(*families)
    (contact_line,) = request_of(*families).lines[1].lines
    faces = plan.faces
    (chain,) = plan.chains
    pair = chain.cell_ids[plan.seeds.role[chain.cell_ids] == SeedRole.MIRROR]
    ends = faces.segment_nodes[int(plan.seeds.pair_id[pair[0]])]
    others = np.delete(faces.vertices, ends, axis=0)
    gap = np.hypot(*(others[:, None, :] - faces.vertices[ends][None]).transpose(2, 0, 1))

    assert plan.family_stats["rivers"]["crossings"] == 1.0
    assert np.hypot(*np.diff(faces.vertices[ends], axis=0)[0]) == pytest.approx(H)
    assert gap.min() >= CROSSING_ABSORB_SHARE * H
    assert len(faces.vertices) < len(contact_line.coords)


def test_a_crossing_beside_a_contact_junction_is_not_opened() -> None:
    plan = plan_of(
        rivers(line((20, 150), (380, 150))),
        contact(line((200, 20), (200, 280)), line((100, 160), (300, 160))),
    )
    (chain,) = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_of_two_contacts_crossing_a_river_half_a_cell_apart_only_the_first_is_opened() -> None:
    plan, _ = situation("two contacts four metres apart across a river")
    (chain,) = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 1.0
    assert np.count_nonzero(plan.seeds.role[chain.cell_ids] == SeedRole.MIRROR) == 2


def test_a_crossing_seed_given_to_a_close_thalweg_is_not_opened() -> None:
    plan = plan_of(
        rivers(line((20, 150), (380, 150)), line((20, 156), (380, 156))),
        contact(line((200, 20), (200, 280))),
    )
    first, second = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert set(second.cell_ids.tolist()) <= set(first.cell_ids.tolist())
    assert plan.family_stats["geology"]["yielded_segments"] > 0


def test_a_crossing_next_to_a_confluence_leaves_the_confluence_to_both_rivers() -> None:
    plan, _ = situation("a confluence two metres beside a contact")
    main, tributary = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert tributary.cell_ids[-1] in main.cell_ids
    assert np.all(plan.seeds.role[main.cell_ids] == SeedRole.CHAIN)


def test_a_river_crossing_near_its_source_keeps_its_own_seeds() -> None:
    plan = plan_of(rivers(line((198, 150), (380, 150))), contact(line((200, 20), (200, 280))))
    (chain,) = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_a_crossing_pair_on_the_source_of_its_river_is_undone() -> None:
    """The source seed lies within 0.05 cell of a pair seed of the crossing: the chain seed wins.

    The crossing segment loses its pair, the crossing is undone and the river takes
    back the seed of the crossing vertex: its chain is its own seeds again.
    """
    plan, _ = situation("a river rising five metres before a contact")
    (chain,) = plan.chains
    seeds = plan.seeds.xy[chain.cell_ids]
    vertex = local((200.0, 150.0))[0]

    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert plan.family_stats["geology"]["yielded_segments"] == 1.0
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)
    assert np.all(chain.offset_m == 0.0)
    assert np.hypot(*(seeds - vertex).T).min() < 1e-9
    assert np.hypot(*(seeds[0] - local((195.0, 150.0))[0])) < 1e-9


def test_a_river_cutting_the_tip_of_a_lake_keeps_its_seeds_where_the_shore_merged() -> None:
    plan, _ = situation("a river cutting the narrow tip of a lake")
    (chain,) = plan.chains
    stats = plan.family_stats["lakes"]
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert stats["merged_circles"] > 0
    assert stats["yielded_segments"] == 0.0
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_a_river_crossing_a_lake_runs_through_a_pair_of_the_shore_at_both_crossings() -> None:
    plan, _ = situation("a river crossing a lake twice")
    (chain,) = plan.chains
    lake = plan.family_names.index("lakes")
    mirror = chain.cell_ids[plan.seeds.role[chain.cell_ids] == SeedRole.MIRROR]
    assert plan.family_stats["rivers"]["crossings"] == 2.0
    assert plan.family_stats["lakes"]["yielded_segments"] == 0.0
    assert mirror.size == 4
    assert np.all(plan.seeds.family[mirror] == lake)


def test_a_pond_smaller_than_a_cell_on_a_river_merges_and_leaves_the_river_alone() -> None:
    plan, _ = situation("a pond smaller than a cell on a river")
    (chain,) = plan.chains
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert plan.family_stats["lakes"]["mirror_pairs"] == 0.0
    assert plan.family_stats["lakes"]["merged_circles"] == np.count_nonzero(
        plan.faces.segment_family == plan.family_names.index("lakes")
    )
    assert np.all(plan.seeds.role[chain.cell_ids] == SeedRole.CHAIN)


def test_a_river_ending_in_a_pond_ends_in_a_cell_of_its_shore() -> None:
    plan, _ = situation("a river ending in a pond smaller than a cell")
    (chain,) = plan.chains
    last = int(chain.cell_ids[-1])
    assert plan.family_stats["rivers"]["crossings"] == 0.0
    assert plan.seeds.role[last] == SeedRole.MIRROR
    assert plan.family_names[plan.seeds.family[last]] == "lakes"


def test_two_lakes_on_either_side_of_a_sill_share_its_faces() -> None:
    plan, _ = situation("two lakes on either side of a sill")
    faces = plan.faces
    pairs = [tuple(sorted(pair)) for pair in faces.segment_nodes.tolist()]
    sill = shapely.get_coordinates(
        shapely.line_interpolate_point(
            LineString(local((200, 100), (200, 200))), np.linspace(0.0, 100.0, 6)
        )
    )
    on_sill = np.isclose(
        faces.vertices[faces.segment_nodes[faces.shared_segment]][:, :, 0], sill[0, 0]
    )

    assert len(pairs) == len(set(pairs))
    assert on_sill.all()
    assert faces.shared_segment.size == round(100.0 / H)
    assert np.all(faces.shared_family == plan.family_names.index("lakes"))
    assert faces.shared_reversed.all()
    assert plan.family_stats["lakes"]["conformal_length_share"] == 1.0


def test_a_contact_following_a_barrier_shares_its_faces_along_its_course() -> None:
    plan = plan_of(
        barriers(line((100, 150), (300, 150))),
        contact(line((50, 50), (100, 150), (300, 150), (350, 250))),
    )
    faces = plan.faces
    barrier = plan.family_names.index(BARRIER_FAMILY)
    assert np.all(faces.segment_family[faces.shared_segment] == barrier)
    assert np.all(faces.shared_family == plan.family_names.index("geology"))
    assert not faces.shared_reversed.any()
    assert faces.shared_segment.size == np.count_nonzero(faces.segment_family == barrier)
    assert plan.family_stats["geology"]["conformal_length_share"] == 1.0


def test_constraint_seeds_lie_in_the_domain() -> None:
    plan = crossing_plan()
    domain = local_frame(DOMAIN).to_local(DOMAIN)
    assert shapely.intersects_xy(domain, plan.seeds.xy[:, 0], plan.seeds.xy[:, 1]).all()


def test_gate_and_lloyd_inputs_follow_the_plan() -> None:
    plan = crossing_plan()
    assert len(mirror_face_runs(plan.faces)) == plan.family_stats["geology"]["mirror_pairs"]
    hard, protect = constraint_disks(plan)
    n_balls = np.count_nonzero(plan.faces.conformal)
    assert len(hard.radius) - n_balls == plan.chains[0].cell_ids.size - 1
    assert len(protect.radius) == plan.seeds.n
    extras = plan.seed_extras()
    assert sum(extras.values()) == plan.seeds.n


def test_a_plan_without_rivers_has_no_gabriel_disk() -> None:
    plan = plan_of(contact(line((100.0, 150.0), (300.0, 150.0))))
    hard, _ = constraint_disks(plan)
    assert len(hard.radius) == np.count_nonzero(plan.faces.conformal)


def test_a_request_without_size_field_is_refused() -> None:
    request = mesh_request(grid_over(DOMAIN, PIXEL), nominal_size_m=H)
    frame = local_frame(DOMAIN)
    field = uniform_size_field(request.grid, H)
    with pytest.raises(MeshRequestError, match="size field"):
        place_constraints(request, frame, SizeSampler(field, frame))


def test_a_contact_beside_a_barrier_yields_to_it() -> None:
    plan = plan_of(
        contact(line((100.0, 156.0), (300.0, 156.0))),
        barriers(line((100.0, 150.0), (300.0, 150.0))),
    )

    assert plan.family_stats[BARRIER_FAMILY]["conformal_length_share"] == 1.0
    assert plan.family_stats["geology"]["yielded_segments"] > 0


def test_a_contact_stopping_short_of_another_loses_its_tip_to_it() -> None:
    plan, _ = situation("a contact stopping eight metres short of another")
    faces = plan.faces
    long_line = faces.segment_line == faces.segment_line.min()
    stats = plan.family_stats["geology"]
    assert stats["free_ends"] == 3.0
    assert stats["yielded_segments"] == 1.0
    assert faces.segment_conformal[long_line].all()


def test_a_crossing_wins_over_a_contact_pair_in_the_ball_of_its_segment() -> None:
    plan, _ = situation("a crossing beside a barrier")
    stats = plan.family_stats
    assert stats["rivers"]["crossings"] == 2.0
    assert stats[BARRIER_FAMILY]["yielded_segments"] == 0.0
    assert stats["geology"]["yielded_segments"] > 0


def test_a_fault_meeting_a_contact_just_above_a_river_yields_to_both() -> None:
    plan, _ = situation("a contact junction thirty centimetres above a river")
    assert plan.family_stats["faults"]["mirror_pairs"] == 0.0
    assert plan.family_stats["geology"]["conformal_length_share"] == 1.0


def test_a_lake_cut_open_by_the_edge_still_holds_against_a_river_beside_it() -> None:
    plan, _ = situation("a lake cut open by the catchment edge beside a river")
    (chain,) = plan.chains
    lake = Polygon(local((0, 100), (150, 100), (150, 200), (0, 200)))
    lake_seeds = chain.cell_ids[plan.seeds.role[chain.cell_ids] == SeedRole.MIRROR]
    assert plan.family_stats["lakes"]["yielded_segments"] == 0.0
    assert plan.family_stats["lakes"]["boundary_ends"] == 2.0
    assert lake_seeds.size > 0
    assert not shapely.contains_xy(lake, *plan.seeds.xy[chain.cell_ids].T).any()


def test_a_river_leaving_at_a_corner_takes_the_corner_seed() -> None:
    plan, _ = situation("a river leaving at a corner")
    corner = local((400.0, 300.0))[0]
    near = np.flatnonzero(np.hypot(*(plan.seeds.xy - corner).T) < 1.0)
    assert near.size == 1
    assert plan.seeds.role[near[0]] == SeedRole.CHAIN


def test_a_hole_smaller_than_a_pixel_has_no_corner_but_seeds_around_its_ring() -> None:
    hole = box(*at(200, 150), *at(202, 152))
    plan = plan_of(domain=with_holes(hole))
    ring_line = local_frame(DOMAIN).to_local(hole).exterior
    on_hole = shapely.distance(shapely.points(plan.seeds.xy), ring_line) < 1.0e-6
    corners = shapely.get_coordinates(ring_line)[:-1]
    at_corner = np.hypot(*(plan.seeds.xy[on_hole][:, None, :] - corners[None]).T).min(axis=0)
    assert np.count_nonzero(on_hole) >= 3
    assert np.count_nonzero(at_corner < 1.0e-6) <= 1


def test_a_round_hole_takes_the_end_seeds_of_a_contact_and_seeds_all_around() -> None:
    plan, domain = situation("a contact from the edge to a round hole")
    hole = local_frame(DOMAIN).to_local(domain).interiors[0]
    on_hole = np.flatnonzero(shapely.distance(shapely.points(plan.seeds.xy), hole) < 1.0e-6)
    ends = on_hole[plan.seeds.vertex_id[on_hole] >= 0]
    angle = np.sort(np.arctan2(*(plan.seeds.xy[on_hole] - local((200.0, 150.0))[0]).T[::-1]))
    gaps = np.diff(np.r_[angle, angle[0] + 2.0 * np.pi])
    assert plan.family_stats["geology"]["boundary_ends"] == 2.0
    assert ends.size == 2
    assert gaps.max() * 40.0 < 1.5 * H


def test_a_round_catchment_has_no_corner_and_seeds_all_around() -> None:
    plan, domain = situation("a round catchment")
    ring_line = local_frame(DOMAIN).to_local(domain).exterior
    on_ring = plan.seeds.xy[(plan.seeds.role == SeedRole.BOUNDARY) & (plan.seeds.vertex_id < 0)]
    angle = np.sort(np.arctan2(*(on_ring - local((200.0, 150.0))[0]).T[::-1]))
    gaps = np.diff(np.r_[angle, angle[0] + 2.0 * np.pi])
    assert shapely.distance(shapely.points(on_ring), ring_line).max() < 1.0e-6
    assert gaps.max() * 140.0 < 1.5 * H


def test_a_contact_ending_on_a_small_round_hole_leaves_only_its_end_seeds_there() -> None:
    plan, domain = situation("a contact ending on a small round hole")
    hole = local_frame(DOMAIN).to_local(domain).interiors[0]
    on_hole = np.flatnonzero(shapely.distance(shapely.points(plan.seeds.xy), hole) < 1.0e-6)
    assert plan.family_stats["geology"]["boundary_ends"] == 1.0
    assert np.all(plan.seeds.vertex_id[on_hole] >= 0)
    assert on_hole.size == 2


def test_a_barrier_on_a_lake_ring_leaves_the_stretch_to_it_and_shares_its_faces() -> None:
    field = uniform_size_field(grid_over(DOMAIN, PIXEL), H)
    shore = (
        resample_families(
            (lakes(ring((100, 100), (300, 100), (300, 200), (100, 200))),),
            domain=DOMAIN,
            size_field=field,
        )
        .families[0]
        .lines[0]
    )
    coords = shapely.get_coordinates(shore)
    on_side = coords[np.isclose(coords[:, 0], X0 + 300.0)]
    on_side = on_side[np.argsort(on_side[:, 1])]
    wings = [at(x, y) for x, y in ((360.0, 100.0), (340.0, 100.0), (320.0, 100.0))]
    wall = LineString([*wings, *map(tuple, on_side), *[(x, y + 100.0) for x, y in wings[::-1]]])
    plan = plan_of(lakes(shore), barriers(wall), resample=False)
    faces = plan.faces

    assert_the_shore_stretch_is_fed_once(plan)
    assert (
        np.count_nonzero(faces.shared_family == plan.family_names.index(BARRIER_FAMILY))
        == len(on_side) - 1
    )
    assert plan.family_stats[BARRIER_FAMILY]["conformal_length_share"] == 1.0
    assert_definition_2(plan)


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
def test_a_cutoff_wall_laid_on_the_reservoir_shore_is_fed_once(
    offset: float, walled_reservoir: Callable[[float], tuple[object, MeshRequest]]
) -> None:
    _, request = walled_reservoir(offset)
    lines = resample_families(request.lines, domain=request.domain, size_field=request.size_field)
    frame = local_frame(request.domain)
    plan = place_constraints(
        mesh_request(
            request.grid,
            domain=request.domain,
            nominal_size_m=request.nominal_size_m,
            lines=lines.families,
            size_field=request.size_field,
        ),
        frame,
        SizeSampler(request.size_field, frame),
    )
    assert_the_shore_stretch_is_fed_once(plan)


@pytest.mark.parametrize("angle", [60.0, 20.0])
def test_a_river_never_makes_a_barrier_yield(angle: float) -> None:
    tangent = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    centre = np.array([200.0, 150.0])
    plan = plan_of(
        rivers(line((20.0, 150.0), (380.0, 150.0))),
        barriers(line(tuple(centre - 140.0 * tangent), tuple(centre + 140.0 * tangent))),
    )
    (chain,) = plan.chains
    barrier = plan.family_names.index(BARRIER_FAMILY)
    stats = plan.family_stats[BARRIER_FAMILY]

    assert stats["yielded_segments"] == 0.0
    assert stats["conformal_length_share"] == 1.0
    assert plan.family_stats["rivers"]["crossings"] == 1.0
    assert np.any(plan.seeds.family[chain.cell_ids] == barrier)
    assert_definition_2(plan)


@pytest.mark.parametrize("angle", [90.0, 30.0, 15.0])
def test_a_river_crosses_a_barrier_once_between_two_chain_cells(
    angle: float, reservoir_request: Callable[..., MeshRequest]
) -> None:
    centre = np.array(reservoir_dam.DOMAIN.centroid.coords[0])
    tangent = np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))])
    barrier = LineString([centre - 250.0 * tangent, centre + 250.0 * tangent])
    x0, y0 = reservoir_dam.X0, reservoir_dam.Y0
    river = LineString(
        [(x0 + 50.0, y0 + 410.0), (x0 + 600.0, y0 + 400.0), (x0 + 1150.0, y0 + 380.0)]
    )
    cell_mesh = VoronoiMeshEngine().build(reservoir_request((barrier,), river=river))
    (chain,) = cell_mesh.chains("rivers")
    links = {
        tuple(sorted(link))
        for link in zip(chain.cell_ids[:-1].tolist(), chain.cell_ids[1:].tolist(), strict=True)
        if link[0] != link[1]
    }
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(BARRIER_FAMILY) & (table.cell_b >= 0)
    faces = {
        tuple(sorted(pair))
        for pair in zip(table.cell_a[rows].tolist(), table.cell_b[rows].tolist(), strict=True)
    }
    nodes = np.asarray(cell_mesh.mesh.vertices, dtype=float)[
        np.concatenate([table.node_a[rows], table.node_b[rows]]), :2
    ]
    qa = cell_mesh.qa.families

    assert len(links & faces) == 1
    assert qa["rivers"]["breaks"] == 0.0
    assert qa[BARRIER_FAMILY]["covered_length_rel"] == pytest.approx(1.0, abs=1.0e-9)
    assert shapely.distance(shapely.points(nodes), barrier).max() < 1.0e-3
    assert qa[BARRIER_FAMILY]["yielded_segments"] == 0.0
    assert qa[BARRIER_FAMILY]["merged_circles"] == 0.0


SHORE_LAKE = box(X0 + 300.0, Y0 + 300.0, X0 + 900.0, Y0 + 600.0)
SHORE_RIVER = LineString(
    [(X0 + 400.0, Y0 + 100.0), (X0 + 420.0, Y0 + 290.0), (X0 + 780.0, Y0 + 290.0)]
)


@functools.cache
def shore_beside_a_river() -> PlanarCellMesh:
    """A lake shore with a river running ten meters from it, meshed at 40 m (fix of 2026-10-20)."""
    return voronoi_lake_mesh(
        shapely.normalize(SHORE_LAKE),
        domain=box(X0, Y0, X0 + 1200.0, Y0 + 900.0),
        pixel=10.0,
        cell_size=40.0,
        rivers=(SHORE_RIVER,),
    )


def test_a_lake_shore_keeps_its_faces_beside_a_river() -> None:
    lakes_qa = shore_beside_a_river().qa.families["lakes"]
    assert lakes_qa["covered_length_rel"] > 1.0 - 1e-6
    assert lakes_qa["yielded_segments"] == 0.0


def test_a_river_beside_a_lake_shore_stays_off_the_lake_and_unbroken() -> None:
    cell_mesh = shore_beside_a_river()
    cells = np.unique(np.concatenate([chain.cell_ids for chain in cell_mesh.chains("rivers")]))
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0
    assert not shapely.contains(SHORE_LAKE, shapely.points(cell_mesh.centers[cells])).any()
