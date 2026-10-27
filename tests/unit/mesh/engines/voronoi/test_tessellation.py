"""Clipped Voronoi cells, boundary seeds for orphans and holes, vertices shared by id."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    VERTEX_MERGE_M,
    cell_topology,
    tessellate,
    voronoi_cells,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over, mesh_request, uniform_size_field

X0, Y0 = L93_ORIGIN
SEED_COUNTS = (
    "n_seeds_chain",
    "n_seeds_mirror",
    "n_seeds_tip",
    "n_seeds_boundary",
    "n_seeds_free",
    "boundary_seeds_added",
)
"""The QA extras that count the generators of a generated mesh."""


def mesh_of(
    world: Polygon, size: float, *families: LineFamilySpec, pixel: float = 5.0
) -> PlanarCellMesh:
    """The generated voronoi mesh of *world* at a constant *size*, lines resampled on it."""
    grid = grid_over(world, pixel)
    field = uniform_size_field(grid, size)
    lines = resample_families(families, domain=world, size_field=field).families
    return VoronoiMeshEngine().build(
        mesh_request(grid, domain=world, nominal_size_m=size, lines=lines, size_field=field)
    )


def test_a_lambert_square_at_five_metres_has_one_cell_per_seed() -> None:
    cell_mesh = mesh_of(box(X0, Y0, X0 + 250.0, Y0 + 250.0), 5.0)
    qa = cell_mesh.qa
    assert cell_mesh.n_cells == sum(qa.extras[name] for name in SEED_COUNTS)
    assert qa.area_sum_rel_error <= 1e-9
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
    cell_mesh = mesh_of(_staircase_u(), 12.0)
    assert cell_mesh.qa.area_sum_rel_error <= 1e-9


def test_a_hole_inside_one_cell_gets_seeds_on_its_ring() -> None:
    hole = box(X0 + 20.0, Y0 + 20.0, X0 + 22.0, Y0 + 22.0)
    world = Polygon(box(X0, Y0, X0 + 100.0, Y0 + 100.0).exterior.coords, [hole.exterior.coords])
    frame = local_frame(world)
    domain = frame.to_local(world)
    seeds = frame.to_local(np.array([[X0 + 10.0, Y0 + 10.0], [X0 + 90.0, Y0 + 90.0]]))
    envelope = voronoi_envelope(domain, 100.0)
    assert shapely.get_num_interior_rings(voronoi_cells(seeds, domain, envelope)[0]) == 1
    tess = tessellate(seeds, 2, domain, envelope)
    added = tess.seeds[2 : tess.n_fixed]
    assert tess.boundary_seeds_added >= 1
    assert shapely.distance(shapely.points(added), frame.to_local(hole).exterior).max() < 1e-9
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


def test_vertices_closer_than_a_millimetre_across_a_key_boundary_merge() -> None:
    frame = local_frame(box(0.0, 0.0, 1.0, 1.0))
    below, above = 10.0 + 0.4 * VERTEX_MERGE_M, 10.0 + 0.6 * VERTEX_MERGE_M
    cells = np.array(
        [
            shapely.Polygon([(0, 0), (below, 0), (below, 10), (0, 10)]),
            shapely.Polygon([(above, 0), (20, 0), (20, 10), (above, 10)]),
        ]
    )
    topology = cell_topology(cells, frame)
    assert len(topology.vertices) == 6
    assert set(topology.rings[0].tolist()) & set(topology.rings[1].tolist()) == {1, 2}


def test_a_frame_wider_than_the_vertex_key_is_refused() -> None:
    frame = LocalFrame((0.0, 0.0))
    far = shapely.box(2.2e6, 0.0, 2.2e6 + 10.0, 10.0)
    with pytest.raises(MeshGenerationError, match=r"2\^31 mm"):
        cell_topology(np.array([box(0, 0, 10, 10), far]), frame)


def test_a_ring_left_with_two_corners_is_a_gate_fault() -> None:
    frame = local_frame(box(0.0, 0.0, 1.0, 1.0))
    sliver = shapely.Polygon([(0, 0), (5e-4, 0), (0, 5e-4)])
    with pytest.raises(MeshGenerationError, match="G5"):
        cell_topology(np.array([box(0, 0, 10, -10), sliver]), frame)


def test_cocircular_mirror_pairs_on_a_line_leave_no_short_face() -> None:
    """A straight contact at a constant step puts four pair seeds on the circle of each vertex.

    GEOS meets the four cells in one point, and the vertex merge leaves no face under 1 mm.
    """
    world = box(X0, Y0, X0 + 200.0, Y0 + 120.0)
    contact = LineString([(X0 + 20.0, Y0 + 60.0), (X0 + 180.0, Y0 + 60.0)])
    cell_mesh = mesh_of(world, 10.0, LineFamilySpec("geology", "face", (contact,), ("n",), ("s",)))
    qa = cell_mesh.qa
    segments = qa.families["geology"]["mirror_pairs"]

    assert segments == contact.length / 10.0
    assert qa.extras["gate_mirror_faces"] == segments
    assert qa.extras["gate_def2_vertices"] == segments + 1
    assert cell_mesh.geometry.edge_length.min() >= VERTEX_MERGE_M
    assert qa.n_duplicate_vertices_in_cells == 0
