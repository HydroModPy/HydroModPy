"""Clipped Voronoi cells, boundary seeds for orphans and holes, vertices shared by id.

``voronoi_planar_mesh`` makes the Voronoi (PEBI) mesh of a set of seeds clipped to a
domain, made of ragged polygon cells centred on their seeds.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.solver.modflow_grid.solver_mesh import to_flopy_disv_args
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    VERTEX_MERGE_M,
    cell_topology,
    tessellate,
    voronoi_cells,
    voronoi_envelope,
    voronoi_planar_mesh,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.request import LineFamilySpec
from hydromodpy.spatial.mesh.resample import resample_families
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
    # The ring point farthest from the seed at (10, 10) is the far corner of the hole. The cell
    # of that new seed wraps the hole in turn, and the corner farthest from it splits the hole.
    far, near = hole.bounds[2:], hole.bounds[:2]
    assert tess.boundary_seeds_added == 2
    assert np.allclose(frame.to_world(added), [far, near])
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


# -- the Voronoi mesh of a set of seeds ----------------------------------------

_DOMAIN = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])


def _jittered_seeds(n_side: int = 12) -> np.ndarray:
    rng = np.random.default_rng(0)
    grid = np.linspace(50.0, 950.0, n_side)
    xx, yy = np.meshgrid(grid, grid)
    return np.c_[xx.ravel(), yy.ravel()] + rng.uniform(-25.0, 25.0, (n_side * n_side, 2))


def _cell_polygons(mesh: HydroMesh) -> list[Polygon]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    return [Polygon(vertices[np.asarray(cell)]) for cell in mesh.flat_connectivity]


def test_voronoi_cells_tile_the_domain_without_gaps_or_overlap() -> None:
    mesh = voronoi_planar_mesh(_jittered_seeds(), _DOMAIN)
    cells = _cell_polygons(mesh)
    union = shapely.union_all(cells)
    assert len(cells) == len(_jittered_seeds())
    assert union.area == pytest.approx(_DOMAIN.area, rel=1e-9)  # full coverage
    assert sum(c.area for c in cells) == pytest.approx(union.area, rel=1e-9)  # no overlap
    assert all(abs(c.area - c.convex_hull.area) < 1e-6 for c in cells)


def test_a_domain_far_from_the_origin_keeps_one_cell_per_seed() -> None:
    # Qhull on Lambert-93 coordinates gave two identical cells for seeds a few metres apart.
    origin = np.array([350_000.0, 6_800_000.0])
    axis = np.arange(2.5, 100.0, 5.0)
    xx, yy = np.meshgrid(axis, axis)
    seeds = np.c_[xx.ravel(), yy.ravel()] + origin
    domain = Polygon(
        [origin, origin + (100.0, 0.0), origin + (100.0, 100.0), origin + (0.0, 100.0)]
    )
    mesh = voronoi_planar_mesh(seeds, domain)
    geometry = derive_geometry(mesh)

    assert mesh.n_cells == len(seeds)
    assert geometry.areas.sum() == pytest.approx(domain.area, rel=1e-9)
    assert geometry.areas == pytest.approx(25.0, rel=1e-9)
    assert np.array_equal(mesh.cell_data["disv_cell_center"], seeds)


def test_two_coincident_seeds_are_refused() -> None:
    from hydromodpy.core.exceptions import MeshGenerationError

    seeds = np.array([[10.0, 10.0], [10.0, 10.0], [60.0, 60.0]])
    with pytest.raises(MeshGenerationError):
        voronoi_planar_mesh(seeds, Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]))


def test_voronoi_planar_mesh_center_is_the_seed() -> None:
    seeds = _jittered_seeds()
    mesh = voronoi_planar_mesh(seeds, _DOMAIN)
    assert mesh.cell_types == (CellType.POLYGON,)
    centers = mesh.cell_data["disv_cell_center"]
    assert centers.shape == (mesh.n_cells, 2)
    kw = to_flopy_disv_args(mesh, top=10.0, botm=np.zeros((1, mesh.n_cells)))
    assert kw["ncpl"] == mesh.n_cells
    # cell2d row = [ic, xc, yc, ncvert, *nodes]; xc/yc must equal the generator seed,
    # not the polygon vertex-mean centroid (exact perpendicular-bisector orthogonality).
    for row, seed in zip(kw["cell2d"], centers, strict=True):
        assert row[1] == pytest.approx(float(seed[0]))
        assert row[2] == pytest.approx(float(seed[1]))
        assert row[3] == len(row) - 4 >= 3  # ncvert matches the listed node count


def test_voronoi_dual_of_a_triangular_mesh() -> None:
    seeds = _jittered_seeds(6)
    tri = HydroMesh(
        vertices=np.c_[seeds, np.zeros(len(seeds))],  # 3-column, z ignored
        cell_blocks=(CellBlock(cell_type=CellType.TRIANGLE, connectivity=np.array([[0, 1, 2]])),),
    )
    dual = voronoi_planar_mesh(np.asarray(tri.vertices)[:, :2], _DOMAIN)
    assert dual.cell_types == (CellType.POLYGON,)
    assert dual.n_cells == len(seeds)  # one Voronoi cell per seed


def test_concave_domain_keeps_every_cell_center_inside_its_cell() -> None:
    # L-shaped (concave) domain: a clip that splits a cell keeps the piece that holds its seed.
    domain = Polygon(
        [
            (0.0, 0.0),
            (1000.0, 0.0),
            (1000.0, 1000.0),
            (500.0, 1000.0),
            (500.0, 500.0),
            (0.0, 500.0),
        ]
    )
    grid = np.linspace(60.0, 940.0, 16)
    xx, yy = np.meshgrid(grid, grid)
    candidates = np.c_[xx.ravel(), yy.ravel()]
    seeds = candidates[[domain.contains(Point(p)) for p in candidates]]
    mesh = voronoi_planar_mesh(seeds, domain)
    cells = _cell_polygons(mesh)
    centers = mesh.cell_data["disv_cell_center"]
    assert len(cells) == len(centers) == len(seeds)
    for cell, center in zip(cells, centers, strict=True):
        assert cell.covers(Point(center))  # DISV center never falls outside its cell
    total = sum(c.area for c in cells)
    assert total <= domain.area * (1.0 + 1e-9)
    assert total >= domain.area * 0.98  # dropped concave slivers stay negligible


def test_seeds_given_in_three_dimensions_are_refused() -> None:
    seeds = np.c_[_jittered_seeds(), np.zeros(len(_jittered_seeds()))]

    with pytest.raises(ValueError, match=r"seeds must have shape \(n, 2\)"):
        voronoi_planar_mesh(seeds, _DOMAIN)


def test_a_seed_whose_cell_only_touches_the_domain_is_refused() -> None:
    """The cell of the last seed meets the square along its east side only, a line of no area."""
    seeds = np.array([[25.0, 50.0], [75.0, 50.0], [125.0, 50.0]])

    with pytest.raises(
        MeshGenerationError, match=r"gate G0: no part of the cell of seed\(s\) \[2\]"
    ):
        voronoi_planar_mesh(seeds, box(0.0, 0.0, 100.0, 100.0))
