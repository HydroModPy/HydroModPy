"""Planar cell meshes adapted from the regular grid, the triangulation and its dual."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.spatial.mesh.adapters.cell_mesh import (
    cell_mesh_from_regular_grid,
    cell_mesh_from_triangulation,
    cell_mesh_from_voronoi_dual,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    build_gmsh_support_metadata,
    support_on_planar_mesh,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_planar_mesh

X0, Y0 = 351_250.0, 6_789_500.0
"""Lambert-93 origin of every mesh here (EPSG:2154)."""
CRS = "EPSG:2154"
SIZE_M = 500.0
N_SIDE = 6
RIVER_ROW = 3


def _square_triangulation() -> tuple[HydroMesh, SimpleNamespace]:
    """A jittered square triangulation and its bundle-like payload.

    The nodes of row ``RIVER_ROW`` are joined by river edges; the cells left of
    ``x = X0 + 250`` are zone ``west``, the others ``east``.
    """
    rng = np.random.default_rng(7)
    axis = np.linspace(0.0, SIZE_M, N_SIDE)
    node_x, node_y = (a.reshape(-1) for a in np.meshgrid(axis, axis))
    spacing = SIZE_M / (N_SIDE - 1)
    inner = (node_x > 0.0) & (node_x < SIZE_M) & (node_y > 0.0) & (node_y < SIZE_M)
    node_x[inner] += rng.uniform(-0.2, 0.2, int(inner.sum())) * spacing
    node_y[inner] += rng.uniform(-0.2, 0.2, int(inner.sum())) * spacing
    node_x += X0
    node_y += Y0
    j, i = np.divmod(np.arange((N_SIDE - 1) ** 2), N_SIDE - 1)
    a = j * N_SIDE + i
    triangles = np.vstack(
        [
            np.column_stack([a, a + 1, a + N_SIDE + 1]),
            np.column_stack([a, a + N_SIDE + 1, a + N_SIDE]),
        ]
    )
    zone = np.where(node_x[triangles].mean(axis=1) < X0 + 250.0, "west", "east")

    owners: dict[tuple[int, int], list[int]] = {}
    for cell, tri in enumerate(triangles.tolist()):
        for k in range(3):
            p, q = tri[k], tri[(k + 1) % 3]
            owners.setdefault((min(p, q), max(p, q)), []).append(cell)
    river = {(RIVER_ROW * N_SIDE + k, RIVER_ROW * N_SIDE + k + 1) for k in range(N_SIDE - 1)}
    edges = []
    for edge_id, (key, cells) in enumerate(owners.items()):
        cell_b = cells[1] if len(cells) > 1 else None
        kind = "boundary" if cell_b is None else "internal"
        if cell_b is not None and zone[cells[0]] != zone[cell_b]:
            kind = "geology_interface"
        edges.append(
            SimpleNamespace(
                edge_id=edge_id,
                node_a=key[0],
                node_b=key[1],
                cell_a=cells[0],
                cell_b=cell_b,
                edge_kind=kind,
                is_river=key in river,
                geology_a_key=str(zone[cells[0]]),
                geology_b_key="" if cell_b is None else str(zone[cell_b]),
            )
        )
    bundle = SimpleNamespace(
        bundle_dir=".",
        mesh_path="mesh_2d.msh",
        nodes=tuple(
            SimpleNamespace(node_id=k, x=float(x), y=float(y))
            for k, (x, y) in enumerate(zip(node_x, node_y, strict=True))
        ),
        cells=tuple(
            SimpleNamespace(
                cell_id=c,
                node_indices=tuple(tri),
                centroid_x=float(node_x[tri].mean()),
                centroid_y=float(node_y[tri].mean()),
            )
            for c, tri in enumerate(triangles)
        ),
        edges=tuple(edges),
    )
    mesh = HydroMesh(
        vertices=np.column_stack([node_x, node_y]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),),
    )
    return mesh, bundle


def _node_pairs(nodes_a: np.ndarray, nodes_b: np.ndarray) -> set[tuple[int, int]]:
    return {(min(p, q), max(p, q)) for p, q in zip(nodes_a.tolist(), nodes_b.tolist(), strict=True)}


def _family_pairs(cell_mesh, family: str) -> set[tuple[int, int]]:
    rows = cell_mesh.face_rows(family)
    table = cell_mesh.face_families
    return _node_pairs(table.node_a[rows], table.node_b[rows])


# -- regular -----------------------------------------------------------------


def test_regular_adapter_keeps_the_grid_vertices_and_quads() -> None:
    grid = RegularGrid(shape=(3, 4), dx=25.0, dy=50.0, origin=(X0, Y0))
    cell_mesh = cell_mesh_from_regular_grid(grid, crs_wkt=CRS)
    reference = grid.to_hydro_mesh()

    np.testing.assert_array_equal(cell_mesh.mesh.vertices, reference.vertices)
    np.testing.assert_array_equal(cell_mesh.mesh.flat_connectivity, reference.flat_connectivity)
    assert cell_mesh.mesh.flat_connectivity[0].tolist() == [0, 1, 6, 5]
    assert cell_mesh.mesh.flat_connectivity[5].tolist() == [6, 7, 12, 11]
    assert cell_mesh.mesh.vertices[0].tolist() == [X0, Y0]
    assert cell_mesh.structured_shape == (3, 4)
    assert cell_mesh.center_kind == "cell_center"
    assert cell_mesh.identity.engine_id == "regular"
    assert cell_mesh.identity.request_hash == ""
    assert cell_mesh.crs_wkt == CRS


def test_regular_adapter_centres_are_cell_centres_row_zero_north() -> None:
    grid = RegularGrid(shape=(3, 4), dx=25.0, dy=50.0, origin=(X0, Y0))
    cell_mesh = cell_mesh_from_regular_grid(grid, crs_wkt=CRS)

    assert cell_mesh.centers[0].tolist() == [X0 + 12.5, Y0 - 25.0]
    assert cell_mesh.centers[4].tolist() == [X0 + 12.5, Y0 - 75.0]
    np.testing.assert_allclose(cell_mesh.centers, cell_mesh.geometry.area_centroids, atol=1e-6)
    assert cell_mesh.qa.area_sum_rel_error == pytest.approx(0.0, abs=1e-15)
    assert cell_mesh.qa.nonorthogonality_deg["max"] == pytest.approx(0.0, abs=1e-6)
    assert cell_mesh.qa.declarations["deterministic"] is True


# -- triangles ---------------------------------------------------------------


def test_triangle_adapter_families_are_the_support_river_and_boundary_edges() -> None:
    mesh, bundle = _square_triangulation()
    support = build_gmsh_support_metadata(bundle)
    cell_mesh = cell_mesh_from_triangulation(mesh, support, crs_wkt=CRS)

    river = np.flatnonzero(support.edge_is_river)
    assert _family_pairs(cell_mesh, "rivers") == _node_pairs(
        support.edge_node_a_index[river], support.edge_node_b_index[river]
    )
    labelled = np.isin(support.edge_ids, list(support.boundary_labels_by_edge_id))
    sides = set()
    for side in ("west", "east", "south", "north"):
        assert cell_mesh.face_rows(f"boundary:{side}").any()
        sides |= _family_pairs(cell_mesh, f"boundary:{side}")
    assert sides == _node_pairs(
        support.edge_node_a_index[labelled], support.edge_node_b_index[labelled]
    )
    boundary_rows = np.array(
        [name.startswith("boundary:") for name in cell_mesh.face_families.names]
    )
    on_boundary = boundary_rows[cell_mesh.face_families.family]
    assert np.all(cell_mesh.face_families.cell_b[on_boundary] == -1)
    np.testing.assert_array_equal(
        np.sort(cell_mesh.family_cells("rivers")), support.river_cell_indices()
    )


def test_triangle_adapter_maps_geology_zones() -> None:
    mesh, bundle = _square_triangulation()
    support = build_gmsh_support_metadata(bundle)
    cell_mesh = cell_mesh_from_triangulation(mesh, support, crs_wkt=CRS)
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")
    contact = np.flatnonzero(np.asarray(support.edge_kind) == "geology_interface")

    assert cell_mesh.zone_names == ("east", "west")
    assert int(rows.sum()) == contact.size > 0
    left = np.asarray(cell_mesh.zone_names)[table.zone_left[rows]]
    right = np.asarray(cell_mesh.zone_names)[table.zone_right[rows]]
    np.testing.assert_array_equal(left, np.asarray(support.geology_a_key)[contact])
    np.testing.assert_array_equal(right, np.asarray(support.geology_b_key)[contact])
    expected = np.where(mesh.vertices[mesh.flat_connectivity].mean(axis=1)[:, 0] < X0 + 250.0, 1, 0)
    np.testing.assert_array_equal(cell_mesh.cell_zone, expected)


def test_triangle_adapter_centres_are_vertex_means() -> None:
    mesh, bundle = _square_triangulation()
    cell_mesh = cell_mesh_from_triangulation(
        GmshPlanarMesh2D.from_hydro_mesh(mesh), build_gmsh_support_metadata(bundle), crs_wkt=CRS
    )
    xs, ys = mesh.cell_centroids()

    assert cell_mesh.center_kind == "vertex_mean"
    np.testing.assert_allclose(cell_mesh.centers, np.column_stack([xs, ys]), rtol=0.0, atol=1e-9)
    assert cell_mesh.identity.engine_id == "triangle"
    assert cell_mesh.qa.center_offset["max"] == pytest.approx(0.0, abs=1e-9)


def test_triangle_adapter_without_support_has_no_family() -> None:
    mesh, _ = _square_triangulation()
    cell_mesh = cell_mesh_from_triangulation(mesh, None, crs_wkt=CRS)

    assert cell_mesh.face_families is None
    assert cell_mesh.cell_zone is None
    assert cell_mesh.qa.families == {}


def test_a_support_of_other_cells_is_refused() -> None:
    mesh, bundle = _square_triangulation()
    support = build_gmsh_support_metadata(bundle)
    dual = voronoi_planar_mesh(np.asarray(mesh.vertices)[:, :2], domain_polygon_from_mesh(mesh))

    with pytest.raises(ValueError, match="cells"):
        cell_mesh_from_voronoi_dual(dual, support, crs_wkt=CRS)


def test_a_support_of_permuted_cells_is_refused() -> None:
    mesh, bundle = _square_triangulation()
    support = build_gmsh_support_metadata(bundle)
    order = np.random.default_rng(0).permutation(mesh.n_cells)
    permuted = HydroMesh(
        vertices=mesh.vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(mesh.flat_connectivity)[order]),),
    )

    with pytest.raises(ValueError, match="cell order"):
        cell_mesh_from_triangulation(permuted, support, crs_wkt=CRS)


def test_a_support_edge_that_is_not_a_mesh_edge_is_refused() -> None:
    mesh, bundle = _square_triangulation()
    support = build_gmsh_support_metadata(bundle)
    node_a = np.array(support.edge_node_a_index, copy=True)
    node_b = np.array(support.edge_node_b_index, copy=True)
    node_b[0] = (int(node_a[0]) + 2 * N_SIDE) % mesh.n_nodes
    broken = dataclasses.replace(support, edge_node_b_index=node_b)

    with pytest.raises(ValueError, match="not a mesh edge"):
        cell_mesh_from_triangulation(mesh, broken, crs_wkt=CRS)


# -- Voronoi dual ------------------------------------------------------------


def test_voronoi_adapter_centres_are_the_generators_and_families_the_dual_support() -> None:
    mesh, bundle = _square_triangulation()
    dual = voronoi_planar_mesh(np.asarray(mesh.vertices)[:, :2], domain_polygon_from_mesh(mesh))
    support = support_on_planar_mesh(build_gmsh_support_metadata(bundle), dual)
    cell_mesh = cell_mesh_from_voronoi_dual(dual, support, crs_wkt=CRS)

    assert cell_mesh.center_kind == "generator"
    np.testing.assert_array_equal(cell_mesh.centers, dual.cell_data["disv_cell_center"])
    river = np.flatnonzero(support.edge_is_river)
    assert river.size > 0
    assert _family_pairs(cell_mesh, "rivers") == _node_pairs(
        support.edge_node_a_index[river], support.edge_node_b_index[river]
    )
    np.testing.assert_array_equal(cell_mesh.family_cells("rivers"), support.river_cell_indices())
    assert any(name.startswith("boundary:") for name in cell_mesh.face_families.names)
    assert cell_mesh.identity.engine_id == "voronoi"
    assert cell_mesh.qa.nonorthogonality_deg["max"] < 1e-6


def test_voronoi_adapter_needs_the_generators() -> None:
    mesh, bundle = _square_triangulation()
    dual = voronoi_planar_mesh(np.asarray(mesh.vertices)[:, :2], domain_polygon_from_mesh(mesh))
    support = support_on_planar_mesh(build_gmsh_support_metadata(bundle), dual)
    bare = HydroMesh(vertices=dual.vertices, cell_blocks=dual.cell_blocks)

    with pytest.raises(ValueError, match="disv_cell_center"):
        cell_mesh_from_voronoi_dual(bare, support, crs_wkt=CRS)
