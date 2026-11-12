"""Clipped Voronoi cells, boundary seeds for orphans and holes, vertices shared by id.

``voronoi_planar_mesh`` makes the Voronoi (PEBI) mesh of a set of seeds clipped to a
domain, made of ragged polygon cells centered on their seeds.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import Point, Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.mesh.engines.voronoi.local_coords import LocalFrame, local_frame
from hydromodpy.mesh.engines.voronoi.tessellation import (
    cell_topology,
    tessellate,
    voronoi_cells,
    voronoi_envelope,
    voronoi_planar_mesh,
)
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import VERTEX_MERGE_M, derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import LineFamilySpec
from hydromodpy.mesh.resample import resample_families
from hydromodpy.solver.modflow_grid.solver_mesh import to_flopy_disv_args
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


def test_orphan_piece_boundary_seed() -> None:
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


def test_hole_inside_one_cell() -> None:
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


def test_close_vertices_merge() -> None:
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


def test_frame_wider_than_the_vertex_key() -> None:
    frame = LocalFrame((0.0, 0.0))
    far = shapely.box(2.2e6, 0.0, 2.2e6 + 10.0, 10.0)
    with pytest.raises(MeshGenerationError, match=r"2\^31 mm"):
        cell_topology(np.array([box(0, 0, 10, 10), far]), frame)


def test_g5_ring_with_two_corners() -> None:
    frame = local_frame(box(0.0, 0.0, 1.0, 1.0))
    sliver = shapely.Polygon([(0, 0), (5e-4, 0), (0, 5e-4)])
    with pytest.raises(MeshGenerationError, match="G5"):
        cell_topology(np.array([box(0, 0, 10, -10), sliver]), frame)


_DOMAIN = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])


def _jittered_seeds(n_side: int = 12) -> np.ndarray:
    rng = np.random.default_rng(0)
    grid = np.linspace(50.0, 950.0, n_side)
    xx, yy = np.meshgrid(grid, grid)
    return np.c_[xx.ravel(), yy.ravel()] + rng.uniform(-25.0, 25.0, (n_side * n_side, 2))


def _cell_polygons(mesh: HydroMesh) -> list[Polygon]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    return [Polygon(vertices[row[row >= 0]]) for row in mesh.flat_connectivity]


def test_cells_tile_the_domain() -> None:
    mesh = voronoi_planar_mesh(_jittered_seeds(), _DOMAIN)
    cells = _cell_polygons(mesh)
    union = shapely.union_all(cells)
    assert len(cells) == len(_jittered_seeds())
    assert union.area == pytest.approx(_DOMAIN.area, rel=1e-9)  # full coverage
    assert sum(c.area for c in cells) == pytest.approx(union.area, rel=1e-9)  # no overlap
    assert all(abs(c.area - c.convex_hull.area) < 1e-6 for c in cells)


def test_domain_far_from_the_origin() -> None:
    # Qhull on Lambert-93 coordinates gave two identical cells for seeds a few meters apart.
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
    assert all(
        cell.covers(Point(seed)) for cell, seed in zip(_cell_polygons(mesh), seeds, strict=True)
    )


def test_two_coincident_seeds_are_refused() -> None:
    seeds = np.array([[10.0, 10.0], [10.0, 10.0], [60.0, 60.0]])
    with pytest.raises(MeshGenerationError):
        voronoi_planar_mesh(seeds, Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]))


def test_disv_export_uses_the_seeds() -> None:
    seeds = _jittered_seeds()
    mesh = voronoi_planar_mesh(seeds, _DOMAIN)
    assert mesh.cell_types == (CellType.POLYGON,)
    kw = to_flopy_disv_args(mesh, top=10.0, botm=np.zeros((1, mesh.n_cells)), centers=seeds)
    assert kw["ncpl"] == mesh.n_cells
    # cell2d row = [ic, xc, yc, ncvert, *nodes]; xc/yc must equal the generator seed,
    # not the polygon vertex-mean centroid (exact perpendicular-bisector orthogonality).
    for row, seed in zip(kw["cell2d"], seeds, strict=True):
        assert row[1] == pytest.approx(float(seed[0]))
        assert row[2] == pytest.approx(float(seed[1]))
        assert row[3] == len(row) - 4 >= 3  # ncvert matches the listed node count


def test_three_dimensional_seeds() -> None:
    seeds = np.c_[_jittered_seeds(), np.zeros(len(_jittered_seeds()))]

    with pytest.raises(ValueError, match=r"seeds must have shape \(n, 2\)"):
        voronoi_planar_mesh(seeds, _DOMAIN)


def test_seed_cell_touching_the_domain() -> None:
    """The cell of the last seed meets the square along its east side only, a line of no area."""
    seeds = np.array([[25.0, 50.0], [75.0, 50.0], [125.0, 50.0]])

    with pytest.raises(
        MeshGenerationError, match=r"gate G0: no part of the cell of seed\(s\) \[2\]"
    ):
        voronoi_planar_mesh(seeds, box(0.0, 0.0, 100.0, 100.0))
