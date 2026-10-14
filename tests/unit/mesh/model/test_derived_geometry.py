"""Derived geometry of a planar mesh against hand-written reference builders."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import (
    derive_geometry,
    derive_geometry_from_rows,
)
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import voronoi_planar_mesh

X0, Y0 = 351_250.0, 6_789_500.0
"""A Lambert-93 corner (EPSG:2154)."""


def _quads() -> HydroMesh:
    return RegularGrid(shape=(4, 5), dx=20.0, dy=10.0, origin=(0.0, 40.0)).to_hydro_mesh()


def _triangles() -> HydroMesh:
    rng = np.random.default_rng(3)
    axis = np.linspace(0.0, 300.0, 7)
    xx, yy = np.meshgrid(axis, axis)
    xy = np.column_stack([xx.ravel(), yy.ravel()])
    inner = np.all((xy > 0.0) & (xy < 300.0), axis=1)
    xy[inner] += rng.uniform(-10.0, 10.0, (int(inner.sum()), 2))
    j, i = np.divmod(np.arange(36), 6)
    a = j * 7 + i
    tris = np.vstack([np.column_stack([a, a + 1, a + 8]), np.column_stack([a, a + 8, a + 7])])
    return HydroMesh(vertices=xy, cell_blocks=(CellBlock(CellType.TRIANGLE, tris),))


def _voronoi() -> HydroMesh:
    rng = np.random.default_rng(0)
    grid = np.linspace(50.0, 950.0, 10)
    xx, yy = np.meshgrid(grid, grid)
    seeds = np.c_[xx.ravel(), yy.ravel()] + rng.uniform(-25.0, 25.0, (100, 2))
    domain = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])
    return voronoi_planar_mesh(seeds, domain)


def _shifted(mesh: HydroMesh, dx: float, dy: float) -> HydroMesh:
    return HydroMesh(
        vertices=mesh.vertices + np.array([dx, dy]),
        cell_blocks=mesh.cell_blocks,
        structured_shape=mesh.structured_shape,
    )


def _polygons(mesh: HydroMesh) -> np.ndarray:
    rings = [shapely.linearrings(mesh.vertices[np.asarray(c)]) for c in mesh.flat_connectivity]
    return shapely.polygons(rings)


def _legacy_areas(mesh: HydroMesh) -> np.ndarray:
    """The former shoelace of ``SolverMesh.cell_areas``: a loop on the raw coordinates."""
    rows = mesh.flat_connectivity
    areas = np.zeros(mesh.n_cells)
    for cell, nodes in enumerate(rows):
        x, y = mesh.vertices[np.asarray(nodes)].T
        areas[cell] = abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    return areas


def _shared_edge_neighbours(mesh: HydroMesh) -> list[set[int]]:
    """Cells that share an edge (an unordered pair of consecutive nodes), by a dict of edges."""
    owners: dict[tuple[int, int], list[int]] = {}
    for cell, nodes in enumerate(mesh.flat_connectivity):
        ring = [int(node) for node in nodes]
        for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
            owners.setdefault((min(a, b), max(a, b)), []).append(cell)
    adjacency: list[set[int]] = [set() for _ in range(mesh.n_cells)]
    for cells in owners.values():
        if len(cells) == 2:
            adjacency[cells[0]].add(cells[1])
            adjacency[cells[1]].add(cells[0])
    return adjacency


MESHES = {"quads": _quads, "triangles": _triangles, "voronoi": _voronoi}


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_adjacency_and_areas_match_the_reference_builders(kind: str) -> None:
    mesh = MESHES[kind]()
    geometry = derive_geometry(mesh)

    assert geometry.adjacency_sets() == _shared_edge_neighbours(mesh)
    np.testing.assert_allclose(geometry.areas, _legacy_areas(mesh), rtol=1e-12, atol=0.0)


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_area_centroids_match_shapely(kind: str) -> None:
    mesh = MESHES[kind]()
    geometry = derive_geometry(mesh)
    polygons = _polygons(mesh)

    np.testing.assert_allclose(
        geometry.area_centroids,
        shapely.get_coordinates(shapely.centroid(polygons)),
        rtol=0.0,
        atol=1e-9,
    )


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_lambert93_coordinates_keep_areas_and_centroids_exact(kind: str) -> None:
    local = derive_geometry(MESHES[kind]())
    lambert = derive_geometry(_shifted(MESHES[kind](), X0, Y0))

    # The shift rounds each vertex to the 1e-9 m spacing of doubles near 6.8e6.
    np.testing.assert_allclose(lambert.areas, local.areas, rtol=1e-10, atol=0.0)
    np.testing.assert_allclose(lambert.area_centroids - [X0, Y0], local.area_centroids, atol=1e-7)


def test_regular_grid_in_lambert93_has_exact_cell_areas() -> None:
    grid = RegularGrid(shape=(30, 40), dx=25.0, dy=25.0, origin=(X0, Y0))
    geometry = derive_geometry(grid.to_hydro_mesh())

    np.testing.assert_allclose(geometry.areas, 625.0, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_adjacency_is_csr_with_sorted_unique_symmetric_neighbours(kind: str) -> None:
    geometry = derive_geometry(MESHES[kind]())
    indptr, indices = geometry.adjacency_indptr, geometry.adjacency_indices

    assert indptr[0] == 0 and indptr[-1] == indices.size
    assert np.all(np.diff(indptr) >= 0)
    for cell in range(geometry.n_cells):
        row = geometry.neighbours(cell)
        assert np.all(np.diff(row) > 0)
        assert cell not in row
        assert all(cell in geometry.neighbours(other) for other in row)


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_edge_table_marks_the_boundary_with_minus_one(kind: str) -> None:
    mesh = MESHES[kind]()
    geometry = derive_geometry(mesh)
    boundary = geometry.edge_cells[:, 1] < 0
    interior = ~boundary

    assert np.all(geometry.edge_cells[boundary, 1] == -1)
    assert np.all(geometry.edge_cells[interior, 0] < geometry.edge_cells[interior, 1])
    assert np.all(geometry.edge_nodes[:, 0] < geometry.edge_nodes[:, 1])
    perimeter = geometry.edge_length[boundary].sum()
    outline = shapely.union_all(_polygons(mesh))
    assert perimeter == pytest.approx(outline.length, rel=1e-12)


def test_quads_have_their_known_edge_table() -> None:
    geometry = derive_geometry(_quads())

    assert geometry.edge_nodes.shape == (4 * 6 + 5 * 5, 2)
    assert int((geometry.edge_cells[:, 1] < 0).sum()) == 2 * (4 + 5)
    np.testing.assert_allclose(np.unique(geometry.edge_length), [10.0, 20.0])
    assert geometry.padded_connectivity.dtype == np.int32
    assert geometry.neighbours(6).tolist() == [1, 5, 7, 11]


def test_ragged_rows_are_padded_with_minus_one() -> None:
    mesh = _voronoi()
    geometry = derive_geometry(mesh)
    padded = geometry.padded_connectivity

    for cell, nodes in enumerate(mesh.flat_connectivity):
        assert padded[cell, : nodes.size].tolist() == nodes.tolist()
        assert np.all(padded[cell, nodes.size :] == -1)


def test_an_edge_shared_by_three_cells_raises() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0], [0.5, -1.0], [0.5, 2.0]])
    triangles = np.array([[0, 1, 2], [1, 0, 3], [0, 1, 4]])
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),))

    with pytest.raises(ValueError, match="shared by 3 cells"):
        derive_geometry(mesh)


def test_a_repeated_corner_is_no_face() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
    cells = (np.array([0, 1, 1, 2, 3]), np.array([1, 4, 5, 2]))
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
    geometry = derive_geometry(mesh)

    assert geometry.edge_nodes.shape[0] == 7
    assert np.all(geometry.edge_length > 0.0)
    assert geometry.adjacency_sets() == [{1}, {0}]
    np.testing.assert_allclose(geometry.areas, [1.0, 1.0])


def test_a_mesh_with_3d_vertices_raises() -> None:
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2]]),))

    with pytest.raises(ValueError, match="2-column"):
        derive_geometry(mesh)


@pytest.mark.parametrize("build", [_quads, _triangles, _voronoi])
def test_the_geometry_of_stored_rows_is_the_geometry_of_the_mesh(build) -> None:
    """A reader holding the padded int32 rows of a store derives what the mesh derived."""
    mesh = build()
    expected = derive_geometry(mesh)
    vertices3 = np.column_stack([mesh.vertices, np.zeros(mesh.n_nodes)])

    from_rows = derive_geometry_from_rows(vertices3, expected.padded_connectivity)

    for name in (
        "padded_connectivity",
        "areas",
        "area_centroids",
        "edge_nodes",
        "edge_cells",
        "edge_length",
        "edge_midpoint",
        "adjacency_indptr",
        "adjacency_indices",
    ):
        np.testing.assert_array_equal(getattr(from_rows, name), getattr(expected, name))
