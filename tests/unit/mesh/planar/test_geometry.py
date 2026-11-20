"""Derived geometry of a planar mesh against hand-written reference builders."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import (
    cell_areas,
    cell_polygons,
    derive_geometry,
    derive_geometry_from_rows,
    padded_rows,
    polygon_rings,
    vertex_keys,
)
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh

X0, Y0 = L93_ORIGIN


def _quads() -> HydroMesh:
    return regular_mesh(4, 5, dx=20.0, dy=10.0).mesh


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


TRIANGLE_VERTICES = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])


def _shifted(mesh: HydroMesh, dx: float, dy: float) -> HydroMesh:
    return HydroMesh(
        vertices=mesh.vertices + np.array([dx, dy]),
        cell_blocks=mesh.cell_blocks,
        structured_shape=mesh.structured_shape,
    )


def _polygons(mesh: HydroMesh) -> np.ndarray:
    rings = [shapely.linearrings(mesh.vertices[c[c >= 0]]) for c in mesh.flat_connectivity]
    return shapely.polygons(rings)


def _legacy_areas(mesh: HydroMesh) -> np.ndarray:
    """The former shoelace of ``SolverMesh.cell_areas``: a loop on the raw coordinates."""
    rows = mesh.flat_connectivity
    areas = np.zeros(mesh.n_cells)
    for cell, nodes in enumerate(rows):
        x, y = mesh.vertices[nodes[nodes >= 0]].T
        areas[cell] = abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    return areas


def _shared_edge_neighbours(mesh: HydroMesh) -> list[set[int]]:
    """Cells that share an edge (an unordered pair of consecutive nodes), by a dict of edges."""
    owners: dict[tuple[int, int], list[int]] = {}
    for cell, nodes in enumerate(mesh.flat_connectivity):
        ring = [int(node) for node in nodes if node >= 0]
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
def test_adjacency_and_areas(kind: str) -> None:
    mesh = MESHES[kind]()
    geometry = derive_geometry(mesh)

    assert geometry.adjacency_sets() == _shared_edge_neighbours(mesh)
    np.testing.assert_allclose(geometry.areas, _legacy_areas(mesh), rtol=1e-12, atol=0.0)


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_area_centroids(kind: str) -> None:
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
def test_lambert93_shift_keeps_geometry(kind: str) -> None:
    local = derive_geometry(MESHES[kind]())
    lambert = derive_geometry(_shifted(MESHES[kind](), X0, Y0))

    # The shift rounds each vertex to the 1e-9 m spacing of doubles near 6.8e6.
    np.testing.assert_allclose(lambert.areas, local.areas, rtol=1e-10, atol=0.0)
    np.testing.assert_allclose(lambert.area_centroids - [X0, Y0], local.area_centroids, atol=1e-7)


def test_lambert93_grid_areas() -> None:
    geometry = derive_geometry(regular_mesh(30, 40, dx=25.0, xmin=X0, ymin=Y0).mesh)

    np.testing.assert_allclose(geometry.areas, 625.0, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_edge_table_boundary(kind: str) -> None:
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


def test_quads_edge_table() -> None:
    geometry = derive_geometry(_quads())

    assert geometry.edge_nodes.shape == (4 * 6 + 5 * 5, 2)
    assert int((geometry.edge_cells[:, 1] < 0).sum()) == 2 * (4 + 5)
    np.testing.assert_allclose(np.unique(geometry.edge_length), [10.0, 20.0])
    assert geometry.padded_connectivity.dtype == np.int32
    assert geometry.neighbours(6).tolist() == [1, 5, 7, 11]


def test_repeated_corner_is_no_face() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
    cells = (np.array([0, 1, 1, 2, 3]), np.array([1, 4, 5, 2]))
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
    geometry = derive_geometry(mesh)

    assert geometry.edge_nodes.shape[0] == 7
    assert np.all(geometry.edge_length > 0.0)
    assert geometry.adjacency_sets() == [{1}, {0}]
    np.testing.assert_allclose(geometry.areas, [1.0, 1.0])


def test_empty_polygon_block() -> None:
    mesh = HydroMesh(
        vertices=TRIANGLE_VERTICES,
        cell_blocks=(CellBlock(CellType.POLYGON, ()), CellBlock(CellType.TRIANGLE, [[0, 1, 2]])),
    )

    geometry = derive_geometry(mesh)

    assert geometry.n_cells == 1
    np.testing.assert_allclose(geometry.areas, [0.5])


def test_padded_rows() -> None:
    ragged = [np.array([0, 1, 2]), np.array([3.0, np.nan, 4.0, 9.0, 5.0])]
    dense = np.array([[0, -1, 2], [3, 7, 1]])

    np.testing.assert_array_equal(padded_rows(ragged, n_nodes=6), [[0, 1, 2], [3, 4, 5]])
    np.testing.assert_array_equal(padded_rows(dense, n_nodes=6), [[0, -1, 2], [3, -1, 1]])
    assert padded_rows([], n_nodes=6).shape == (0, 0)


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_cell_areas_match_geometry(kind: str) -> None:
    mesh = _shifted(MESHES[kind](), X0, Y0)
    geometry = derive_geometry(mesh)

    np.testing.assert_array_equal(
        cell_areas(mesh.vertices, geometry.padded_connectivity), geometry.areas
    )
    np.testing.assert_allclose(
        geometry.areas,
        shapely.area(cell_polygons(mesh.vertices - [X0, Y0], geometry.padded_connectivity)),
        rtol=1e-9,
    )


def test_table_without_slot_has_zero_area() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0]])

    assert cell_areas(vertices, np.empty((3, 0), dtype=int)).tolist() == [0.0, 0.0, 0.0]
    assert cell_areas(vertices, np.empty((0, 4), dtype=int)).size == 0


def test_geometry_without_edge() -> None:
    # One cell whose three corners are one vertex has no side long enough to be an edge.
    geometry = derive_geometry_from_rows(np.array([[0.0, 0.0], [1.0, 0.0]]), np.array([[0, 0, 0]]))

    assert geometry.edge_nodes.shape == (0, 2)
    np.testing.assert_array_equal(geometry.edge_ids([0], [1]), [-1])
    np.testing.assert_array_equal(geometry.edge_between([0], [0]), [-1])


def test_polygon_ring_order() -> None:
    holed = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (4, 2), (4, 4), (2, 4)]])
    other = box(20.0, 0.0, 30.0, 10.0)

    rings = polygon_rings(MultiPolygon([holed, other]), None)

    assert [ring.coords[:] for ring in rings] == [
        holed.exterior.coords[:],
        holed.interiors[0].coords[:],
        other.exterior.coords[:],
    ]
    assert {ring.geom_type for ring in rings} == {"LineString"}


WEDGE_VERTICES = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.1, 0.1], [0.9, 0.1], [0.1, 0.9]])

REFUSALS = [
    pytest.param(
        HydroMesh(
            vertices=TRIANGLE_VERTICES,
            cell_blocks=(CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 1]),)),),
        ),
        "cell 0 uses one edge twice",
        id="outline runs back along an edge",
    ),
    pytest.param(
        HydroMesh(
            vertices=WEDGE_VERTICES,
            cell_blocks=(CellBlock(CellType.WEDGE, [[0, 1, 2, 3, 4, 5]]),),
        ),
        r"not a planar cell type: \['wedge'\]",
        id="volume cell",
    ),
    pytest.param(
        HydroMesh(
            vertices=np.zeros((3, 3)),
            cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2]]),),
        ),
        "2-column",
        id="3d vertices",
    ),
]


@pytest.mark.parametrize(("mesh", "reason"), REFUSALS)
def test_refusals(mesh, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        derive_geometry(mesh)


def test_far_point_refused() -> None:
    with pytest.raises(MeshGenerationError, match="2\\^31 mm"):
        vertex_keys(np.array([[2.2e6, 0.0]]))
