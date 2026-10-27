"""Each gate stops the build with a message that names its faults in Lambert-93."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame
from hydromodpy.spatial.mesh.engines.voronoi.gates import (
    BergeBalls,
    MirrorFaces,
    check_gates,
    gated_geometry,
)
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    cell_topology,
    voronoi_cells,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain
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


def _balls() -> BergeBalls:
    return BergeBalls(
        center=LINE,
        radius=[RADIUS, RADIUS, RADIUS],
        indptr=[0, 3, 7, 10],
        members=[0, 1, 4, 0, 1, 2, 3, 2, 3, 5],
        family=[0, 0, 0],
        line_id=[7, 7, 7],
        vertex_id=[0, 1, 2],
        names=("geology",),
    )


def _faces(plus=(0, 2), minus=(1, 3)) -> MirrorFaces:
    return MirrorFaces(
        plus=plus,
        minus=minus,
        start=LINE[:2],
        end=LINE[1:],
        family=[0, 0],
        line_id=[7, 7],
        segment_id=[0, 1],
        names=("geology",),
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
    report = _check(seeds, balls=_balls(), faces=_faces(), chains=(chain,))
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
        _check(seeds, balls=_balls())
    message = str(raised.value)
    assert "G1: 1" in message
    assert f"'geology' line 7 vertex 1 at ({X0:.3f}, {Y0:.3f})" in message
    assert f"seed(s) 12 at ({X0 + 1.0:.3f}, {Y0 + 3.0:.3f})" in message


def test_a_pair_without_its_face_on_the_line_fails_g2() -> None:
    seeds = np.vstack([PAIRS, FILL])
    with pytest.raises(MeshGenerationError, match=r"G2: 1.*seeds 0 and 3 share no face"):
        _check(seeds, faces=_faces(plus=(0, 2), minus=(3, 3)))


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
    faces = MirrorFaces(
        plus=[0],
        minus=[0],
        start=LINE[:1],
        end=LINE[1:2],
        family=[0],
        line_id=[7],
        segment_id=[0],
        names=("geology",),
    )
    with pytest.raises(MeshGenerationError, match="G2: 1"):
        check_gates(
            seeds=np.zeros((1, 2)),
            cells=np.array([shapely.box(-20.0, -10.0, 20.0, 10.0)]),
            vertices=vertices,
            geometry=derive_geometry(mesh),
            domain_area=800.0,
            frame=FRAME,
            faces=faces,
        )


def test_gate_inputs_refuse_rows_that_do_not_match() -> None:
    with pytest.raises(ValueError, match="MirrorFaces.minus needs 2 rows, got 1"):
        _faces(minus=(1,))
    with pytest.raises(ValueError, match="indptr does not span members"):
        BergeBalls(
            center=LINE,
            radius=[RADIUS] * 3,
            indptr=[0, 3, 7, 9],
            members=list(range(10)),
            family=[0, 0, 0],
            line_id=[7, 7, 7],
            vertex_id=[0, 1, 2],
            names=("geology",),
        )


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
