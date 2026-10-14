"""Clipped Voronoi cells, boundary seeds for orphans and holes, vertices shared by id."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.frame import local_frame
from hydromodpy.spatial.mesh.engines.voronoi.gates import BergeBalls, MirrorFaces
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    VERTEX_MERGE_M,
    cell_topology,
    tessellate,
    voronoi_cells,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.mesh_qa import compute_mesh_qa
from hydromodpy.spatial.mesh.planning.input_mesh import domain_polygon_of, read_input_triangulation
from tests.unit.mesh.engines.voronoi.core_pipeline import X0, Y0, core_mesh, size_field

REPO = Path(__file__).resolve().parents[5]
BUNDLES = REPO / "validation_cases" / "shared" / "mesh_bundles"
GOLDEN = Path(__file__).resolve().parent / "golden"
DECLARATIONS = {"graded": True, "exact_faces": True, "deterministic": True, "needs_cache": False}


def test_a_lambert_square_at_five_metres_has_one_cell_per_seed() -> None:
    domain = box(X0, Y0, X0 + 250.0, Y0 + 250.0)
    mesh = core_mesh(domain, size_field(domain, 5.0, 5.0), cap=3)
    assert mesh.geometry.n_cells == len(mesh.tessellation.seeds)
    assert mesh.gates.area_rel_error <= 1e-9
    qa = compute_mesh_qa(
        mesh.mesh,
        mesh.frame.to_world(mesh.tessellation.seeds),
        mesh.geometry,
        declarations=DECLARATIONS,
    )
    assert qa.n_duplicate_vertices_in_cells == 0
    assert qa.n_degenerate_faces == 0


def _staircase_u() -> Polygon:
    """A U in pixel steps: two arms of 100 m joined at the bottom."""
    return Polygon(
        [
            (X0, Y0),
            (X0 + 250.0, Y0),
            (X0 + 250.0, Y0 + 200.0),
            (X0 + 150.0, Y0 + 200.0),
            (X0 + 150.0, Y0 + 75.0),
            (X0 + 125.0, Y0 + 75.0),
            (X0 + 125.0, Y0 + 50.0),
            (X0 + 100.0, Y0 + 50.0),
            (X0 + 100.0, Y0 + 200.0),
            (X0, Y0 + 200.0),
        ]
    )


def test_an_orphan_piece_gets_a_boundary_seed_and_the_area_closes() -> None:
    world = _staircase_u()
    frame = local_frame(world)
    domain = frame.to_local(world)
    seeds = frame.to_local(
        np.array([[X0 + 90.0, Y0 + 190.0], [X0 + 50.0, Y0 + 20.0], [X0 + 240.0, Y0 + 10.0]])
    )
    envelope = voronoi_envelope(domain, 100.0)
    cells = voronoi_cells(seeds, domain, envelope)
    assert shapely.area(cells).sum() < domain.area * (1.0 - 1e-3)
    tess = tessellate(seeds, 3, domain, envelope)
    assert tess.boundary_seeds_added >= 1
    assert tess.n_fixed == 3 + tess.boundary_seeds_added
    assert np.array_equal(tess.seeds[:3], seeds)
    assert shapely.intersects(domain.boundary, shapely.points(tess.seeds[3:])).all()
    assert abs(shapely.area(tess.cells).sum() - domain.area) <= 1e-9 * domain.area


def test_a_staircase_domain_meshes_with_its_gates_green() -> None:
    world = _staircase_u()
    mesh = core_mesh(world, size_field(world, 5.0, 12.0), cap=5)
    assert mesh.gates.area_rel_error <= 1e-9


def test_a_hole_inside_one_cell_gets_seeds_on_its_ring() -> None:
    world = Polygon(
        box(X0, Y0, X0 + 100.0, Y0 + 100.0).exterior.coords,
        [box(X0 + 20.0, Y0 + 20.0, X0 + 22.0, Y0 + 22.0).exterior.coords],
    )
    frame = local_frame(world)
    domain = frame.to_local(world)
    seeds = frame.to_local(np.array([[X0 + 10.0, Y0 + 10.0], [X0 + 90.0, Y0 + 90.0]]))
    envelope = voronoi_envelope(domain, 100.0)
    assert shapely.get_num_interior_rings(voronoi_cells(seeds, domain, envelope)[0]) == 1
    tess = tessellate(seeds, 2, domain, envelope)
    # The first seed on the ring takes the whole hole in its own cell; the second splits it.
    assert tess.boundary_seeds_added == 2
    assert np.allclose(
        frame.to_world(tess.seeds[2:]), [[X0 + 22.0, Y0 + 22.0], [X0 + 20.0, Y0 + 20.0]]
    )
    assert (shapely.get_num_interior_rings(tess.cells) == 0).all()
    assert abs(shapely.area(tess.cells).sum() - domain.area) <= 1e-9 * domain.area


def test_coincident_seeds_raise() -> None:
    domain = box(-50.0, -50.0, 50.0, 50.0)
    seeds = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 0.0]])
    with pytest.raises(MeshGenerationError, match="coincide"):
        voronoi_cells(seeds, domain, voronoi_envelope(domain, 10.0))


def test_close_vertices_merge_and_repeated_corners_go() -> None:
    frame = local_frame(box(0.0, 0.0, 1.0, 1.0))
    eps = 0.2 * VERTEX_MERGE_M
    cells = np.array(
        [
            shapely.Polygon([(0, 0), (10, 0), (10, 10), (10 + eps, 10 + eps), (0, 10)]),
            shapely.Polygon([(10, 0), (20, 0), (20, 10), (10 + eps, 10 - eps)]),
        ]
    )
    topology = cell_topology(cells, frame)
    assert len(topology.vertices) == 6
    assert [len(ring) for ring in topology.rings] == [4, 4]
    assert topology.rings[0][2] == topology.rings[1][3]
    assert np.array_equal(topology.vertices[topology.rings[0][2]], [10.0, 10.0])


def test_a_ring_left_with_two_corners_is_a_gate_fault() -> None:
    frame = local_frame(box(0.0, 0.0, 1.0, 1.0))
    sliver = shapely.Polygon([(0, 0), (5e-4, 0), (0, 5e-4)])
    with pytest.raises(MeshGenerationError, match="G5"):
        cell_topology(np.array([box(0, 0, 10, -10), sliver]), frame)


def test_cocircular_mirror_pairs_on_a_line_leave_no_short_face() -> None:
    """Four pair seeds lie on the circle of each inner vertex: GEOS meets them in one point."""
    world = box(X0, Y0, X0 + 200.0, Y0 + 120.0)
    vertices = np.column_stack([np.arange(20.0, 181.0, 10.0), np.full(17, 60.0)])
    radius = 0.55 * 10.0
    middle = 0.5 * (vertices[:-1] + vertices[1:])
    lift = [0.0, np.sqrt(radius**2 - 5.0**2)]
    fixed = np.column_stack([middle + lift, middle - lift]).reshape(-1, 2)
    inner = np.arange(1, len(vertices) - 1)
    balls = BergeBalls(
        center=vertices[inner],
        radius=np.full(len(inner), radius),
        indptr=4 * np.arange(len(inner) + 1),
        members=np.column_stack([2 * inner - 2, 2 * inner - 1, 2 * inner, 2 * inner + 1]).ravel(),
        family=np.zeros(len(inner)),
        line_id=np.zeros(len(inner)),
        vertex_id=inner,
        names=("geology",),
    )
    segments = np.arange(1, len(middle) - 1)
    faces = MirrorFaces(
        plus=2 * segments,
        minus=2 * segments + 1,
        start=vertices[segments],
        end=vertices[segments + 1],
        family=np.zeros(len(segments)),
        line_id=np.zeros(len(segments)),
        segment_id=segments,
        names=("geology",),
    )
    mesh = core_mesh(world, size_field(world, 5.0, 10.0), fixed=fixed, balls=balls, faces=faces)
    assert mesh.gates.mirror_faces == len(segments)
    assert mesh.gates.def2_vertices == len(inner)
    assert mesh.geometry.edge_length.min() >= VERTEX_MERGE_M
    qa = compute_mesh_qa(
        mesh.mesh,
        mesh.frame.to_world(mesh.tessellation.seeds),
        mesh.geometry,
        declarations=DECLARATIONS,
    )
    assert qa.n_duplicate_vertices_in_cells == 0


@pytest.mark.parametrize(
    "bundle",
    [
        "dupuit_circular_island_ocean_irregular_tri_radial_48",
        "stream_depletion_glover_balmer_tri_refined_well",
    ],
)
def test_the_tessellation_of_a_triangulation_keeps_the_faces_of_the_old_dual(bundle: str) -> None:
    """The golden froze ``ops/voronoi.voronoi_planar_mesh`` at c710a26a5 (Qhull, 1 mm rounding).

    The faces are the same set; the areas differ by the old rounding of
    cocircular vertices to the millimetre (2.5e-6 relative on the radial island).
    """
    golden = np.load(GOLDEN / f"old_dual_{bundle}.npz")
    triangulation = read_input_triangulation(BUNDLES / bundle / "mesh_2d.msh")
    world = domain_polygon_of(triangulation)
    frame = local_frame(world)
    domain = frame.to_local(world)
    seeds = frame.to_local(np.asarray(triangulation.vertices, dtype=float)[:, :2])
    extent = max(np.ptp(seeds, axis=0))
    cells = voronoi_cells(seeds, domain, voronoi_envelope(domain, extent))
    topology = cell_topology(cells, frame)
    mesh = HydroMesh(
        vertices=frame.to_world(topology.vertices),
        cell_blocks=(CellBlock(CellType.POLYGON, topology.rings),),
    )
    geometry = derive_geometry(mesh)
    faces = np.ascontiguousarray(geometry.edge_cells[geometry.edge_cells[:, 1] >= 0])
    faces = faces[np.lexsort((faces[:, 1], faces[:, 0]))].astype(np.int64)
    assert len(faces) == int(golden["n_faces"])
    assert hashlib.sha256(faces.tobytes()).hexdigest() == str(golden["faces_sha256"])
    assert np.allclose(geometry.areas, golden["areas"], rtol=1e-5, atol=0.0)
