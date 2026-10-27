"""The Voronoi (PEBI) mesh of a set of seeds clipped to a domain, made of ragged polygon cells."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import Point, Polygon

from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_planar_mesh

_DOMAIN = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])


def _jittered_seeds(n_side: int = 12) -> np.ndarray:
    rng = np.random.default_rng(0)
    grid = np.linspace(50.0, 950.0, n_side)
    xx, yy = np.meshgrid(grid, grid)
    return np.c_[xx.ravel(), yy.ravel()] + rng.uniform(-25.0, 25.0, (n_side * n_side, 2))


# -- generator ---------------------------------------------------------------


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


def test_heterogeneous_field_samples_on_voronoi_polygon_cells() -> None:
    # A support field discretized through PolygonFieldMesh must not crash on the
    # ragged POLYGON cells and must produce valid area fractions.
    from hydromodpy.spatial.domain.spatial_support import GeneratedBandsSupportField
    from hydromodpy.spatial.field.meshes.polygon_field_mesh import PolygonFieldMesh

    mesh = voronoi_planar_mesh(_jittered_seeds(), _DOMAIN)
    field_mesh = PolygonFieldMesh(mesh)
    support = GeneratedBandsSupportField(
        identifier="k", axis="x", breaks_abs=[500.0], labels=["west", "east"]
    )
    disc = support.on_mesh(field_mesh, cell_samples_per_axis=8)
    west = np.asarray(disc.fractions_by_zone["west"], dtype=float)
    east = np.asarray(disc.fractions_by_zone["east"], dtype=float)
    assert west.shape == (mesh.n_cells,)
    assert np.all(west >= -1e-9) and np.all(west <= 1.0 + 1e-9)
    assert np.allclose(west + east, 1.0, atol=1e-9)
    xs, _ = mesh.cell_centroids()
    deep_west = np.flatnonzero(xs < 300.0)
    assert deep_west.size > 0
    assert np.all(west[deep_west] > 0.99)


def test_seeds_given_in_three_dimensions_are_refused() -> None:
    seeds = np.c_[_jittered_seeds(), np.zeros(len(_jittered_seeds()))]

    with pytest.raises(ValueError, match=r"seeds must have shape \(n, 2\)"):
        voronoi_planar_mesh(seeds, _DOMAIN)


# -- outline of a mesh ---------------------------------------------------------


def test_the_outline_of_a_mesh_keeps_the_hole_of_its_domain() -> None:
    hole = Polygon([(400.0, 400.0), (600.0, 400.0), (600.0, 600.0), (400.0, 600.0)])
    domain = _DOMAIN.difference(hole)
    seeds = _jittered_seeds()
    seeds = seeds[shapely.contains_xy(domain, *seeds.T)]
    mesh = voronoi_planar_mesh(seeds, domain)

    outline = domain_polygon_from_mesh(mesh)

    assert len(outline.interiors) == 1
    assert outline.area == pytest.approx(derive_geometry(mesh).areas.sum(), rel=1e-9)


def test_a_mesh_without_a_boundary_edge_has_no_outline() -> None:
    """Every edge of a triangle written twice is shared by two cells, so none bounds the mesh."""
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    doubled = HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(cell_type=CellType.TRIANGLE, connectivity=np.array([[0, 1, 2]] * 2)),
        ),
    )

    with pytest.raises(ValueError, match="could not reconstruct a domain polygon"):
        domain_polygon_from_mesh(doubled)
