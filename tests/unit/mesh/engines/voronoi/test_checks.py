"""Each gate stops the build with a message that names its faults in Lambert-93."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import shapely
from shapely.geometry import box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.mesh.engines.voronoi.checks import (
    check_gates,
    gated_geometry,
    mirror_face_runs,
)
from hydromodpy.mesh.engines.voronoi.constraints.plan import (
    ConstraintPlan,
    ConstraintSeeds,
    FaceLineState,
)
from hydromodpy.mesh.engines.voronoi.constraints.state import SeedRole
from hydromodpy.mesh.engines.voronoi.local_coords import LocalFrame
from hydromodpy.mesh.engines.voronoi.tessellation import (
    cell_topology,
    voronoi_cells,
    voronoi_envelope,
)
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain
from tests._helpers.mesh_cases import L93_ORIGIN

X0, Y0 = L93_ORIGIN
FRAME = LocalFrame(L93_ORIGIN)
DOMAIN = box(-50.0, -30.0, 50.0, 30.0)
LINE = np.array([[-20.0, 0.0], [0.0, 0.0], [20.0, 0.0]])
RADIUS = 0.55 * 20.0
LIFT = np.sqrt(RADIUS**2 - 10.0**2)
PAIRS = np.array(
    [[-10.0, LIFT], [-10.0, -LIFT], [10.0, LIFT], [10.0, -LIFT], [-31.0, 0.0], [31.0, 0.0]]
)  # seeds 0..3: pairs of segments 0 and 1 (plus, minus); 4, 5: tips on the tangents at the ends
FILL = np.array(
    [[-40.0, 20.0], [-40.0, -20.0], [40.0, 20.0], [40.0, -20.0], [0.0, 22.0], [0.0, -22.0]]
)


def _plan(
    pairs=((0, 1), (2, 3)),
    *,
    line: np.ndarray = LINE,
    seeds: np.ndarray = PAIRS,
    tips=(0, 2),
    radius: float = RADIUS,
) -> ConstraintPlan:
    """The plan of one ``geology`` line 7 along *line*, its segments fed by *pairs*.

    Its constraint seeds are *seeds*: the pairs of the segments, then a tip seed
    on the sphere of each vertex of *tips*. Every vertex and segment is conformal.
    """
    n_vertex, n_segment = len(line), len(line) - 1
    n_seed = len(seeds)
    vertex_id = np.full(n_seed, -1, dtype=np.int64)
    vertex_id[n_seed - len(tips) :] = tips
    role = np.where(vertex_id >= 0, SeedRole.FREE_END, SeedRole.MIRROR)
    constraint = ConstraintSeeds(
        xy=np.asarray(seeds, dtype=float),
        role=role,
        line_id=np.full(n_seed, 7),
        pair_id=np.full(n_seed, -1),
        vertex_id=vertex_id,
        radius=np.full(n_seed, 20.0),
        family=np.zeros(n_seed, dtype=np.int16),
    )
    faces = FaceLineState(
        vertices=np.asarray(line, dtype=float),
        radius=np.full(n_vertex, radius),
        conformal=np.ones(n_vertex, dtype=bool),
        segment_nodes=np.column_stack([np.arange(n_segment), np.arange(1, n_vertex)]),
        segment_seeds=np.asarray(pairs, dtype=np.int64).reshape(n_segment, 2),
        segment_conformal=np.ones(n_segment, dtype=bool),
        segment_family=np.zeros(n_segment, dtype=np.int64),
        segment_line=np.full(n_segment, 7),
        zone_left=np.full(n_segment, -1, dtype=np.int32),
        zone_right=np.full(n_segment, -1, dtype=np.int32),
    )
    return ConstraintPlan(
        seeds=constraint,
        faces=faces,
        chains=(),
        family_names=("geology",),
        zone_names=(),
        source_lines={},
        family_stats={},
    )


def _mesh(seeds: np.ndarray):
    cells = voronoi_cells(seeds, DOMAIN, voronoi_envelope(DOMAIN, 20.0))
    topology = cell_topology(cells, FRAME)
    mesh = HydroMesh(
        vertices=FRAME.to_world(topology.vertices),
        cell_blocks=(CellBlock(CellType.POLYGON, topology.rings),),
    )
    return cells, topology, gated_geometry(mesh)


def _check(seeds: np.ndarray, **kwargs):
    cells, topology, geometry = _mesh(seeds)
    arguments = {
        "seeds": seeds,
        "cells": cells,
        "vertices": topology.vertices,
        "geometry": geometry,
        "domain_area": DOMAIN.area,
        "frame": FRAME,
    }
    arguments.update(kwargs)
    return check_gates(**arguments)


def test_conformal_pairs_pass_every_gate_and_give_their_face_rows() -> None:
    seeds = np.vstack([PAIRS, FILL])
    chain = CellChain("rivers", 0, np.array([6, 10, 8]))
    report = _check(seeds, plan=_plan(), chains=(chain,))
    assert report.def2_vertices == 3
    assert report.mirror_faces == 2
    assert report.chain_links == 2
    assert report.area_rel_error <= 1e-9
    _, topology, geometry = _mesh(seeds)
    nodes = topology.vertices[geometry.edge_nodes[report.face_rows]]
    assert np.allclose(np.sort(nodes[:, :, 0], axis=1), [[-20.0, 0.0], [0.0, 20.0]], atol=1e-9)
    assert np.allclose(nodes[:, :, 1], 0.0, atol=1e-9)


def test_a_seed_in_a_berge_ball_is_named_with_its_vertex() -> None:
    intruder = np.array([[1.0, 3.0]])
    seeds = np.vstack([PAIRS, FILL, intruder])
    with pytest.raises(MeshGenerationError) as raised:
        _check(seeds, plan=_plan())
    message = str(raised.value)
    assert "G1: 1" in message
    assert f"'geology' line 7 vertex 1 at ({X0:.3f}, {Y0:.3f})" in message
    assert f"seed(s) 12 at ({X0 + 1.0:.3f}, {Y0 + 3.0:.3f})" in message


def test_a_pair_without_its_face_on_the_line_fails_g2() -> None:
    seeds = np.vstack([PAIRS, FILL])
    with pytest.raises(MeshGenerationError, match=r"G2: 1.*seeds 0 and 3 share no face") as raised:
        _check(seeds, plan=_plan(pairs=((0, 3), (2, 3))))
    assert "G1" not in str(raised.value)


def test_a_chain_through_cells_that_are_not_neighbours_fails_g3() -> None:
    seeds = np.vstack([PAIRS, FILL])
    chain = CellChain("rivers", 2, np.array([6, 6, 9]))
    with pytest.raises(MeshGenerationError, match=r"G3: 1.*chain 'rivers' 2: cells 6 .* and 9"):
        _check(seeds, chains=(chain,))


def test_a_missing_area_fails_g4_and_points_at_a_touching_hole() -> None:
    seeds = np.vstack([PAIRS, FILL])
    with pytest.raises(MeshGenerationError, match="G4: 1.*hole touching another ring"):
        _check(seeds, domain_area=DOMAIN.area * 1.001)


def test_an_area_in_excess_fails_g4_without_the_hole_hint() -> None:
    seeds = np.vstack([PAIRS, FILL])
    with pytest.raises(MeshGenerationError, match="G4: 1") as raised:
        _check(seeds, domain_area=DOMAIN.area * 0.999)
    assert "hole" not in str(raised.value)


def test_a_seed_without_its_cell_fails_g0() -> None:
    seeds = np.vstack([PAIRS, FILL])
    cells, topology, geometry = _mesh(seeds)
    n = len(seeds)
    with pytest.raises(
        MeshGenerationError, match=rf"G0: 1.*{n} mesh cells and {n} clipped cells for {n + 1} seeds"
    ):
        check_gates(
            seeds=np.vstack([seeds, [[0.0, 25.0]]]),
            cells=cells,
            vertices=topology.vertices,
            geometry=geometry,
            domain_area=DOMAIN.area,
            frame=FRAME,
        )


def test_a_pair_on_a_mesh_of_one_cell_fails_g2() -> None:
    vertices = np.array([[-20.0, -10.0], [20.0, -10.0], [20.0, 10.0], [-20.0, 10.0]])
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, (np.arange(4),)),))
    plan = _plan(pairs=((0, 0),), line=LINE[:2], seeds=np.zeros((1, 2)), tips=(), radius=1.0)
    with pytest.raises(MeshGenerationError, match="G2: 1"):
        check_gates(
            seeds=np.zeros((1, 2)),
            cells=np.array([shapely.box(-20.0, -10.0, 20.0, 10.0)]),
            vertices=vertices,
            geometry=derive_geometry(mesh),
            domain_area=800.0,
            frame=FRAME,
            plan=plan,
        )


def test_segments_sharing_one_pair_make_one_face_from_the_first_start_to_the_last_end() -> None:
    assert mirror_face_runs(_plan().faces).tolist() == [[0, 0], [1, 1]]
    assert mirror_face_runs(_plan(pairs=((0, 1), (0, 1))).faces).tolist() == [[0, 1]]
    faces = _plan().faces
    open_end = dataclasses.replace(faces, conformal=np.array([True, True, False]))
    assert mirror_face_runs(open_end).tolist() == [[0, 0]]


def test_a_seed_outside_its_cell_fails_g0() -> None:
    seeds = np.vstack([PAIRS, FILL])
    cells, topology, geometry = _mesh(seeds)
    moved = seeds.copy()
    moved[7] = [45.0, 25.0]
    with pytest.raises(MeshGenerationError, match=r"G0: 1.*seed 7 at .*outside its cell"):
        check_gates(
            seeds=moved,
            cells=cells,
            vertices=topology.vertices,
            geometry=geometry,
            domain_area=DOMAIN.area,
            frame=FRAME,
        )


def _two_squares(top_left: tuple[float, float]) -> tuple[np.ndarray, HydroMesh]:
    vertices = np.array([[0, 0], [1, 0], [2, 0], [2, 1], [1, 1], top_left, [0, 1]], dtype=float)
    rings = (np.array([0, 1, 4, 5, 6]), np.array([1, 2, 3, 4]))
    return vertices, HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, rings),))


def test_a_face_under_a_micrometre_fails_g6_and_a_repeated_vertex_g5() -> None:
    vertices, mesh = _two_squares((1.0 - 1e-7, 1.0))
    cells = np.array([shapely.box(0, 0, 1, 1), shapely.box(1, 0, 2, 1)])
    seeds = np.array([[0.5, 0.5], [1.5, 0.5]])
    with pytest.raises(MeshGenerationError, match=r"G6: 1"):
        check_gates(
            seeds=seeds,
            cells=cells,
            vertices=vertices,
            geometry=derive_geometry(mesh),
            domain_area=2.0,
            frame=FRAME,
        )
    repeated = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.POLYGON, (np.array([0, 1, 4, 6, 0, 6]),)),),
    )
    with pytest.raises(MeshGenerationError, match="G5"):
        gated_geometry(repeated)


def test_an_edge_of_three_cells_is_a_gate_fault() -> None:
    vertices = np.array([[0, 0], [1, 0], [0.5, 1], [0.5, -1], [1.5, 0.5]], dtype=float)
    rings = (np.array([0, 1, 2]), np.array([1, 0, 3]), np.array([0, 1, 4]))
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, rings),))
    with pytest.raises(MeshGenerationError, match="G5.*shared by 3 cells"):
        gated_geometry(mesh)


def test_the_message_lists_at_most_twenty_faults() -> None:
    seeds = np.vstack([PAIRS, FILL])
    chains = tuple(CellChain("rivers", k, np.array([6, 9])) for k in range(30))
    with pytest.raises(MeshGenerationError) as raised:
        _check(seeds, chains=chains)
    message = str(raised.value)
    assert "G3: 30" in message
    assert message.count("are not neighbours") == 20
