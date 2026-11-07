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
    BOX_SIDES,
    box_side_of_edges,
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
    geometry = derive_geometry(regular_mesh(30, 40, dx=25.0, xmin=X0, ymin=Y0).mesh)

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


def test_polygon_rows_hold_their_nodes_first_then_minus_one() -> None:
    mesh = _voronoi()
    rows = mesh.flat_connectivity
    used = rows >= 0

    assert len(set(used.sum(axis=1).tolist())) > 1
    assert not np.any(used[:, 1:] & ~used[:, :-1])
    np.testing.assert_array_equal(derive_geometry(mesh).padded_connectivity, rows)


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


def test_a_cell_whose_outline_runs_back_along_one_edge_raises() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    mesh = HydroMesh(
        vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 1]),)),)
    )

    with pytest.raises(ValueError, match="cell 0 uses one edge twice"):
        derive_geometry(mesh)


def test_an_empty_polygon_block_adds_no_cell() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.POLYGON, ()), CellBlock(CellType.TRIANGLE, [[0, 1, 2]])),
    )

    geometry = derive_geometry(mesh)

    assert geometry.n_cells == 1
    np.testing.assert_allclose(geometry.areas, [0.5])


def test_a_volume_cell_on_planar_vertices_raises() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.1, 0.1], [0.9, 0.1], [0.1, 0.9]])
    mesh = HydroMesh(
        vertices=vertices, cell_blocks=(CellBlock(CellType.WEDGE, [[0, 1, 2, 3, 4, 5]]),)
    )

    with pytest.raises(ValueError, match="not a planar cell type: \\['wedge'\\]"):
        derive_geometry(mesh)


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


def test_padded_rows_pack_a_ragged_list_and_keep_a_dense_table_in_place() -> None:
    ragged = [np.array([0, 1, 2]), np.array([3.0, np.nan, 4.0, 9.0, 5.0])]
    dense = np.array([[0, -1, 2], [3, 7, 1]])

    np.testing.assert_array_equal(padded_rows(ragged, n_nodes=6), [[0, 1, 2], [3, 4, 5]])
    np.testing.assert_array_equal(padded_rows(dense, n_nodes=6), [[0, -1, 2], [3, -1, 1]])
    assert padded_rows([], n_nodes=6).shape == (0, 0)


@pytest.mark.parametrize(
    "build", [_quads, _triangles, _voronoi], ids=["quads", "triangles", "voronoi"]
)
def test_the_cell_areas_are_the_areas_of_the_derived_geometry(build) -> None:
    mesh = _shifted(build(), X0, Y0)
    geometry = derive_geometry(mesh)

    np.testing.assert_array_equal(
        cell_areas(mesh.vertices, geometry.padded_connectivity), geometry.areas
    )
    np.testing.assert_allclose(
        geometry.areas,
        shapely.area(cell_polygons(mesh.vertices - [X0, Y0], geometry.padded_connectivity)),
        rtol=1e-9,
    )


def test_a_row_of_fewer_than_three_corners_has_no_area() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])

    np.testing.assert_array_equal(cell_areas(vertices, [[0, 1, -1], [0, -1, -1]]), [0.0, 0.0])


def test_a_table_without_a_slot_has_cells_of_no_area() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0]])

    assert cell_areas(vertices, np.empty((3, 0), dtype=int)).tolist() == [0.0, 0.0, 0.0]
    assert cell_areas(vertices, np.empty((0, 4), dtype=int)).size == 0


def test_a_dense_table_padded_with_negatives_gives_smaller_polygons() -> None:
    vertices = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]])
    padded = np.array([[0, 1, 2, 3], [0, 1, 2, -1]])

    polygons = cell_polygons(vertices, padded)

    assert [polygon.area for polygon in polygons] == [100.0 * 100.0, 0.5 * 100.0 * 100.0]


def test_a_table_padded_with_nan_gives_one_polygon_per_cell() -> None:
    vertices = np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 0.0], [0.0, 100.0], [100.0, 100.0]])
    padded = np.array([[0.0, 1.0, 4.0, 3.0], [1.0, 2.0, 4.0, np.nan]])

    polygons = cell_polygons(vertices, padded)

    assert [polygon.area for polygon in polygons] == [100.0 * 100.0, 0.5 * 100.0 * 100.0]


def test_an_invalid_cell_is_none_unless_it_is_kept() -> None:
    vertices = np.array([[0.0, 0.0], [10.0, 10.0], [10.0, 0.0], [0.0, 10.0], [20.0, 0.0]])
    padded = np.array([[0, 1, 2, 3], [0, 2, 4, -1], [0, 2, -1, -1]])

    dropped = cell_polygons(vertices, padded)
    kept = cell_polygons(vertices, padded, keep_invalid=True)

    assert dropped[0] is None and dropped[1] is None and dropped[2] is None
    assert not kept[0].is_valid
    assert list(kept[0].exterior.coords) == [(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)]
    assert kept[1] is not None and kept[2] is None


def test_the_nodes_around_a_hole_keep_their_order() -> None:
    vertices = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    dense = np.array([[0, -1, 1, 2, 3]])

    polygon = cell_polygons(vertices, dense)[0]

    assert shapely.equals_exact(polygon, cell_polygons(vertices, [np.array([0, 1, 2, 3])])[0], 0.0)


def test_an_edge_is_found_from_its_two_vertices_in_either_order() -> None:
    mesh = _triangles()
    geometry = derive_geometry(mesh)
    node_a, node_b = geometry.edge_nodes.T
    every = np.arange(node_a.size)

    np.testing.assert_array_equal(geometry.edge_ids(node_a, node_b), every)
    np.testing.assert_array_equal(geometry.edge_ids(node_b, node_a), every)
    # Two opposite corners of the box, a negative id and an id past the last vertex.
    far = mesh.n_nodes - 1
    np.testing.assert_array_equal(
        geometry.edge_ids([0, -1, 0], [far, 1, mesh.n_nodes]), [-1, -1, -1]
    )


def test_a_geometry_without_an_edge_finds_none() -> None:
    # One cell whose three corners are one vertex has no side long enough to be an edge.
    geometry = derive_geometry_from_rows(np.array([[0.0, 0.0], [1.0, 0.0]]), np.array([[0, 0, 0]]))

    assert geometry.edge_nodes.shape == (0, 2)
    np.testing.assert_array_equal(geometry.edge_ids([0], [1]), [-1])
    np.testing.assert_array_equal(geometry.edge_between([0], [0]), [-1])


def test_the_edge_between_two_cells_is_the_interior_edge_they_share() -> None:
    geometry = derive_geometry(_quads())
    interior = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)
    cell_a, cell_b = geometry.edge_cells[interior].T

    np.testing.assert_array_equal(geometry.edge_between(cell_b, cell_a), interior)
    np.testing.assert_array_equal(geometry.edge_between([0, 0], [0, 19]), [-1, -1])
    # A cell id outside the mesh never aliases the key of a real pair.
    np.testing.assert_array_equal(geometry.edge_between([-1, 1], [21, 20]), [-1, -1])


def test_two_cells_sharing_several_edges_give_the_first() -> None:
    # A U-shaped cell around a square cell: they share three edges.
    vertices = np.array(
        [[0, 0], [1, 0], [1, 1], [2, 1], [2, 0], [3, 0], [3, 2], [0, 2]], dtype=float
    )
    cells = (np.array([0, 1, 2, 3, 4, 5, 6, 7]), np.array([1, 4, 3, 2]))
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
    geometry = derive_geometry(mesh)
    shared = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)

    assert shared.size == 3
    assert geometry.edge_between([1], [0])[0] == shared.min()


def test_a_boundary_edge_takes_the_side_of_the_box_it_lies_on() -> None:
    mesh = _shifted(_quads(), X0, Y0)
    geometry = derive_geometry(mesh)
    outer = geometry.edge_cells[:, 1] < 0
    inner = ~outer

    sides = box_side_of_edges(mesh.vertices, *geometry.edge_nodes[outer].T)
    middle = box_side_of_edges(mesh.vertices, *geometry.edge_nodes[inner].T)

    counts = np.bincount(sides, minlength=len(BOX_SIDES))
    assert dict(zip(BOX_SIDES, counts.tolist(), strict=True)) == {
        "west": 4,
        "east": 4,
        "south": 5,
        "north": 5,
    }
    assert (middle == -1).all()


def test_the_rings_of_polygons_come_exterior_first_part_after_part() -> None:
    holed = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (4, 2), (4, 4), (2, 4)]])
    other = box(20.0, 0.0, 30.0, 10.0)

    rings = polygon_rings(MultiPolygon([holed, other]), None)

    assert [ring.coords[:] for ring in rings] == [
        holed.exterior.coords[:],
        holed.interiors[0].coords[:],
        other.exterior.coords[:],
    ]
    assert {ring.geom_type for ring in rings} == {"LineString"}


def test_points_within_one_millimetre_cell_share_a_vertex_key() -> None:
    xy = np.array([[0.0, 0.0], [0.0004, -0.0004], [0.0, 0.0006], [-1.0, -2.0], [-1.0002, -2.0003]])

    keys = vertex_keys(xy)

    assert keys[0] == keys[1] != keys[2]
    assert keys[3] == keys[4] != keys[0]


def test_a_point_too_far_for_the_vertex_keys_is_refused() -> None:
    with pytest.raises(MeshGenerationError, match="2\\^31 mm"):
        vertex_keys(np.array([[2.2e6, 0.0]]))
