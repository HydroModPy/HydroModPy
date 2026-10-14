"""Families on built meshes: every case passes the gates G0 to G6 first.

Each build places the constraint seeds, draws the free seeds, relaxes them,
tessellates and runs the gates, as the engine does; the families and the QA
are then read on the mesh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.constraints import ConstraintPlan, place_constraints
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, SizeSampler, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import (
    free_seed_count,
    morton_order,
    sample_free_seeds,
)
from hydromodpy.spatial.mesh.engines.voronoi.gates import check_gates, gated_geometry
from hydromodpy.spatial.mesh.engines.voronoi.line_families import (
    cell_chains,
    cell_zones,
    face_family_table,
)
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import lloyd_invariants, relax
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    cell_topology,
    tessellate,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.mesh_qa import MeshQA, compute_mesh_qa
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest
from tests.unit.mesh.engines.voronoi.core_pipeline import WKT, X0, Y0, size_field

H = 20.0
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)
DECLARATIONS = {"graded": True, "exact_faces": True, "deterministic": True, "needs_cache": False}


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


@dataclass(frozen=True, eq=False)
class Built:
    """A gated mesh with its plan, families and QA."""

    plan: ConstraintPlan
    frame: LocalFrame
    seeds: np.ndarray
    vertices: np.ndarray
    geometry: DerivedGeometry
    chains: tuple[CellChain, ...]
    table: FaceFamilyTable | None
    zones: np.ndarray | None
    qa: MeshQA

    def rows(self, family: str) -> np.ndarray:
        assert self.table is not None
        return np.flatnonzero(self.table.family == self.table.names.index(family))


def build(*families: LineFamilySpec, domain: Polygon = DOMAIN, seed: int = 0) -> Built:
    """Mesh the families like the engine; the gates raise on any fault."""
    field = size_field(domain, 5.0, H)
    lines = resample_families(families, domain=domain, size_field=field).families
    request = MeshRequest(
        domain=domain, crs_wkt=WKT, grid=field.grid, nominal_size_m=H, lines=lines, size_field=field
    )
    frame = local_frame(domain)
    h = SizeSampler(field, frame)
    plan = place_constraints(request, frame, h)
    local = shapely.normalize(frame.to_local(domain))
    fixed = plan.seeds.xy
    rng = np.random.Generator(np.random.PCG64(seed))
    free = sample_free_seeds(
        rng, h, local, fixed, plan.seeds.radius, free_seed_count(h, local, len(fixed))
    )
    balls, faces = plan.berge_balls(), plan.mirror_faces()
    start, end = plan.chain_segments()
    invariants = lloyd_invariants(
        berge_center=balls.center,
        berge_radius=balls.radius,
        chain_start=start,
        chain_end=end,
        constraint_xy=fixed,
        constraint_size=plan.seeds.radius,
    )
    seeds = np.vstack([fixed, free[morton_order(free)]])
    relaxed = relax(seeds, len(fixed), h, local, invariants)
    tess = tessellate(relaxed.seeds, len(fixed), local, voronoi_envelope(local, h.h_max))
    topology = cell_topology(tess.cells, frame)
    mesh = HydroMesh(
        vertices=frame.to_world(topology.vertices),
        cell_blocks=(CellBlock(CellType.POLYGON, topology.rings),),
    )
    geometry = gated_geometry(mesh)
    chains = cell_chains(plan)
    check_gates(
        seeds=tess.seeds,
        cells=tess.cells,
        vertices=topology.vertices,
        geometry=geometry,
        domain_area=local.area,
        frame=frame,
        chains=chains,
        balls=balls,
        faces=faces,
    )
    table = face_family_table(plan, geometry, topology.vertices)
    qa = compute_mesh_qa(
        mesh,
        frame.to_world(tess.seeds),
        geometry,
        declarations=DECLARATIONS,
        domain_area_m2=domain.area,
        lines={
            name: tuple(frame.to_world(part) for part in parts)
            for name, parts in plan.source_lines.items()
        },
        cell_chains=chains,
        face_families=table,
    )
    return Built(
        plan=plan,
        frame=frame,
        seeds=tess.seeds,
        vertices=topology.vertices,
        geometry=geometry,
        chains=chains,
        table=table,
        zones=cell_zones(plan, geometry, topology.vertices, table),
        qa=qa,
    )


def crossing() -> Built:
    angle = math.radians(60.0)
    centre = np.array([200.0, 150.0])
    tangent = np.array([math.cos(angle), math.sin(angle)])
    face = line(tuple(centre - 160.0 * tangent), tuple(centre + 160.0 * tangent))
    return build(rivers(line((20.0, 150.0), (380.0, 150.0))), contact(face))


def assert_faces_on_lines(built: Built, family: str) -> None:
    """Every row of a face family lies on its source lines within 1 mm."""
    table = built.table
    assert table is not None
    rows = built.rows(family)
    ends = built.vertices[np.concatenate([table.node_a[rows], table.node_b[rows]])]
    source = shapely.multilinestrings(list(built.plan.source_lines[family]))
    assert shapely.distance(shapely.points(ends), source).max() < 1.0e-3


def test_a_river_crossing_a_contact_runs_through_the_pair() -> None:
    built = crossing()
    (chain,) = built.chains
    plan = built.plan
    pair = chain.cell_ids[chain.offset_m > 0.0]
    assert pair.size == 2
    assert np.all(plan.seeds.pair_id[pair] == plan.seeds.pair_id[pair[0]])
    assert built.qa.families["rivers"]["breaks"] == 0.0
    assert chain.offset_m[chain.offset_m > 0.0] == pytest.approx(
        np.full(2, built.plan.family_stats["rivers"]["crossing_offset_m_max"])
    )
    assert_faces_on_lines(built, "geology")
    assert built.qa.families["geology"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-6)


def test_the_pair_cells_of_a_contact_take_its_zones() -> None:
    built = crossing()
    plan = built.plan
    assert built.zones is not None
    table = built.table
    assert table is not None
    rows = built.rows("geology")
    left = plan.zone_names.index("l0")
    right = plan.zone_names.index("r0")
    assert np.all(table.zone_left[rows] == left) and np.all(table.zone_right[rows] == right)
    assert np.all(built.zones[table.cell_a[rows]] == left)
    assert np.all(built.zones[table.cell_b[rows]] == right)
    paired = np.zeros(built.geometry.n_cells, dtype=bool)
    paired[np.concatenate([table.cell_a[rows], table.cell_b[rows]])] = True
    assert np.all(built.zones[~paired] == -1)


def test_a_contact_across_the_domain_splits_it_in_two_zones() -> None:
    built = build(contact(line((180.0, 0.0), (220.0, 300.0))))
    plan = built.plan
    assert built.zones is not None
    face = shapely.get_coordinates(plan.source_lines["geology"][0])
    tangent = face[-1] - face[0]
    reach = built.seeds - face[0]
    side = tangent[0] * reach[:, 1] - tangent[1] * reach[:, 0]
    assert np.all(built.zones[side > 0.0] == plan.zone_names.index("l0"))
    assert np.all(built.zones[side < 0.0] == plan.zone_names.index("r0"))


@pytest.mark.parametrize("vertical_end", [150.0, 20.0])
def test_t_and_x_junctions_keep_every_segment(vertical_end: float) -> None:
    built = build(
        contact(line((50.0, 150.0), (350.0, 150.0)), line((200.0, 280.0), (200.0, vertical_end)))
    )
    stats = built.plan.family_stats["geology"]
    assert stats["conformal_length_share"] == 1.0
    assert built.qa.families["geology"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    frame = built.frame
    node = frame.to_local(np.array([[X0 + 200.0, Y0 + 150.0]]))[0]
    vertex = int(np.argmin(np.hypot(*(built.plan.faces.vertices - node).T)))
    assert built.plan.faces.conformal[vertex]
    assert_faces_on_lines(built, "geology")


def test_an_acute_junction_counts_its_mixed_cells() -> None:
    angle = math.radians(15.0)
    tip = (50.0 + 300.0 * math.cos(angle), 100.0 + 300.0 * math.sin(angle))
    built = build(contact(line((50.0, 100.0), (350.0, 100.0)), line((50.0, 100.0), tip)))
    assert built.plan.family_stats["geology"]["merged_circles"] > 0
    assert built.qa.families["geology"]["mixed_cells"] > 0
    assert built.zones is not None
    assert np.count_nonzero(built.zones < 0) > 0


def test_a_free_end_face_runs_to_the_end() -> None:
    built = build(contact(line((100.0, 150.0), (300.0, 150.0))))
    assert built.qa.families["geology"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert built.qa.families["geology"]["mixed_cells"] == 0.0


def test_a_free_end_whose_tip_left_the_domain_is_not_counted_as_followed() -> None:
    built = build(contact(line((200.0, 60.0), (200.0, 295.0))))
    stats = built.plan.family_stats["geology"]
    assert stats["free_ends"] == 1.0
    assert stats["conformal_length_share"] < 1.0
    assert built.qa.families["geology"]["covered_length_rel"] < 1.0


def test_a_hole_touching_the_outer_ring_stops_at_gate_g4_and_says_why() -> None:
    diamond = [(X0 + x, Y0 + y) for x, y in ((100, 0), (180, 60), (100, 120), (20, 60))]
    pinched = Polygon(DOMAIN.exterior.coords, holes=[diamond])
    with pytest.raises(MeshGenerationError, match=r"G4.*touching another ring"):
        build(domain=pinched)


def test_a_contact_ending_on_the_boundary_reaches_it() -> None:
    built = build(contact(line((200.0, 0.0), (200.0, 200.0))))
    assert built.plan.family_stats["geology"]["boundary_ends"] == 1.0
    assert built.qa.families["geology"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert_faces_on_lines(built, "geology")


def test_a_contact_meeting_the_boundary_at_20_degrees_still_builds() -> None:
    angle = math.radians(20.0)
    built = build(
        contact(line((100.0, 0.0), (100.0 + 250.0 * math.cos(angle), 250.0 * math.sin(angle))))
    )
    stats = built.plan.family_stats["geology"]
    assert stats["merged_circles"] + stats["yielded_segments"] > 0


def test_two_close_thalwegs_share_cells_and_stay_continuous() -> None:
    built = build(rivers(line((20.0, 150.0), (380.0, 150.0)), line((20.0, 158.0), (380.0, 158.0))))
    assert built.plan.family_stats["rivers"]["shared_cells"] > 0
    assert built.qa.families["rivers"]["breaks"] == 0.0


def test_a_confluence_cell_is_in_three_chains() -> None:
    built = build(
        rivers(
            line((50.0, 250.0), (200.0, 150.0)),
            line((350.0, 250.0), (200.0, 150.0)),
            line((200.0, 150.0), (200.0, 20.0)),
        )
    )
    common = set(built.chains[0].cell_ids.tolist())
    for chain in built.chains[1:]:
        common &= set(chain.cell_ids.tolist())
    assert len(common) == 1
    assert built.qa.families["rivers"]["breaks"] == 0.0


def test_a_lake_ring_with_a_sharp_turn_is_one_closed_face() -> None:
    ring = line((100.0, 100.0), (300.0, 100.0), (260.0, 200.0), (150.0, 230.0), (100.0, 100.0))
    built = build(LineFamilySpec("lakes", "face", (ring,), closed=True))
    assert built.qa.families["lakes"]["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert built.qa.families["lakes"]["mixed_cells"] == 0.0
    assert_faces_on_lines(built, "lakes")


def test_box_sides_are_boundary_families_with_the_cell_on_the_left() -> None:
    built = build(contact(line((100.0, 150.0), (300.0, 150.0))))
    table = built.table
    assert table is not None
    for side in ("west", "east", "south", "north"):
        rows = built.rows(f"boundary:{side}")
        assert rows.size > 0
        assert np.all(table.cell_b[rows] == -1)
        tangent = built.vertices[table.node_b[rows]] - built.vertices[table.node_a[rows]]
        reach = built.seeds[table.cell_a[rows]] - built.vertices[table.node_a[rows]]
        assert np.all(tangent[:, 0] * reach[:, 1] - tangent[:, 1] * reach[:, 0] >= 0.0)
    outer = built.geometry.edge_cells[:, 1] < 0
    named = sum(built.rows(f"boundary:{s}").size for s in ("west", "east", "south", "north"))
    assert named == np.count_nonzero(outer)


def test_a_mesh_without_lines_has_sides_only_and_no_zones() -> None:
    built = build()
    assert built.table is not None
    assert all(name.startswith("boundary:") for name in built.table.names)
    assert built.zones is None
    assert built.chains == ()


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
    assert np.array_equal(one.vertices, two.vertices)
    assert np.array_equal(one.seeds, two.seeds)
    assert np.array_equal(one.geometry.padded_connectivity, two.geometry.padded_connectivity)
    assert [c.cell_ids.tolist() for c in one.chains] == [c.cell_ids.tolist() for c in two.chains]
    assert one.table is not None and two.table is not None
    assert np.array_equal(one.table.cell_a, two.table.cell_a)
    assert np.array_equal(one.zones, two.zones)
