"""Planar cell meshes adapted from the regular grid and read from a mesh bundle."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.spatial.mesh.adapters.cell_mesh import cell_mesh_from_regular_grid
from hydromodpy.spatial.mesh.gmsh_grid.bundle_cell_mesh import cell_mesh_from_bundle
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid

X0, Y0 = 351_250.0, 6_789_500.0
"""Lambert-93 origin of every mesh here (EPSG:2154)."""
CRS = "EPSG:2154"
SIZE_M = 500.0
N_SIDE = 6
RIVER_ROW = 3


def _square_bundle(*, id_shift: int = 0, river: bool = True) -> SimpleNamespace:
    """A jittered square triangulation as a bundle-like payload.

    The nodes of row ``RIVER_ROW`` are joined by river edges. Node and cell ids
    are the positions plus ``id_shift``.
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
    owners: dict[tuple[int, int], list[int]] = {}
    for cell, tri in enumerate(triangles.tolist()):
        for k in range(3):
            p, q = tri[k], tri[(k + 1) % 3]
            owners.setdefault((min(p, q), max(p, q)), []).append(cell)
    flagged = (
        {(RIVER_ROW * N_SIDE + k, RIVER_ROW * N_SIDE + k + 1) for k in range(N_SIDE - 1)}
        if river
        else set()
    )
    edges = tuple(
        SimpleNamespace(
            edge_id=edge_id,
            node_a=key[0] + id_shift,
            node_b=key[1] + id_shift,
            cell_a=cells[0] + id_shift,
            cell_b=cells[1] + id_shift if len(cells) > 1 else None,
            is_river=key in flagged,
        )
        for edge_id, (key, cells) in enumerate(owners.items())
    )
    return SimpleNamespace(
        nodes=tuple(
            SimpleNamespace(node_id=k + id_shift, x=float(x), y=float(y))
            for k, (x, y) in enumerate(zip(node_x, node_y, strict=True))
        ),
        cells=tuple(
            SimpleNamespace(
                cell_id=c + id_shift, node_indices=tuple(int(n) + id_shift for n in tri)
            )
            for c, tri in enumerate(triangles)
        ),
        edges=edges,
    )


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


# -- bundle ------------------------------------------------------------------


def _boundary_edges(bundle: SimpleNamespace) -> set[tuple[int, int]]:
    return {
        (min(e.node_a, e.node_b), max(e.node_a, e.node_b)) for e in bundle.edges if e.cell_b is None
    }


def test_bundle_cell_mesh_keeps_the_nodes_and_the_triangles_in_file_order() -> None:
    bundle = _square_bundle()
    cell_mesh = cell_mesh_from_bundle(bundle, crs_wkt=CRS)

    np.testing.assert_array_equal(
        cell_mesh.mesh.vertices, [[node.x, node.y] for node in bundle.nodes]
    )
    np.testing.assert_array_equal(
        cell_mesh.mesh.flat_connectivity, [cell.node_indices for cell in bundle.cells]
    )
    assert cell_mesh.center_kind == "vertex_mean"
    assert cell_mesh.identity.engine_id == "triangle"
    assert cell_mesh.crs_wkt == CRS
    xs, ys = cell_mesh.mesh.cell_centroids()
    np.testing.assert_allclose(cell_mesh.centers, np.column_stack([xs, ys]), rtol=0.0, atol=1e-9)


def test_bundle_cell_mesh_ids_are_read_as_positions() -> None:
    plain = cell_mesh_from_bundle(_square_bundle(), crs_wkt=CRS)
    shifted = cell_mesh_from_bundle(_square_bundle(id_shift=10), crs_wkt=CRS)

    np.testing.assert_array_equal(shifted.mesh.flat_connectivity, plain.mesh.flat_connectivity)
    for family in ("rivers", "boundary:west", "boundary:north"):
        for column in ("cell_a", "cell_b", "node_a", "node_b"):
            np.testing.assert_array_equal(
                getattr(shifted.face_families, column)[shifted.face_rows(family)],
                getattr(plain.face_families, column)[plain.face_rows(family)],
            )


def test_bundle_cell_mesh_river_family_is_the_flagged_edges() -> None:
    bundle = _square_bundle()
    cell_mesh = cell_mesh_from_bundle(bundle, crs_wkt=CRS)
    flagged = [e for e in bundle.edges if e.is_river]
    table, rows = cell_mesh.face_families, cell_mesh.face_rows("rivers")

    assert len(flagged) == N_SIDE - 1
    np.testing.assert_array_equal(table.node_a[rows], [e.node_a for e in flagged])
    np.testing.assert_array_equal(table.node_b[rows], [e.node_b for e in flagged])
    np.testing.assert_array_equal(table.cell_a[rows], [e.cell_a for e in flagged])
    np.testing.assert_array_equal(table.cell_b[rows], [e.cell_b for e in flagged])
    expected = {e.cell_a for e in flagged} | {e.cell_b for e in flagged}
    assert set(cell_mesh.family_cells("rivers").tolist()) == expected


def test_bundle_cell_mesh_sides_are_the_boundary_edges_on_the_bounding_box() -> None:
    bundle = _square_bundle()
    cell_mesh = cell_mesh_from_bundle(bundle, crs_wkt=CRS)
    x = {node.node_id: node.x for node in bundle.nodes}
    y = {node.node_id: node.y for node in bundle.nodes}
    sides: set[tuple[int, int]] = set()
    for side, (axis, value) in {
        "west": (x, X0),
        "east": (x, X0 + SIZE_M),
        "south": (y, Y0),
        "north": (y, Y0 + SIZE_M),
    }.items():
        pairs = _family_pairs(cell_mesh, f"boundary:{side}")
        assert pairs
        assert all(axis[p] == axis[q] == value for p, q in pairs)
        sides |= pairs
    assert sides == _boundary_edges(bundle)
    on_boundary = np.array([n.startswith("boundary:") for n in cell_mesh.face_families.names])
    assert np.all(cell_mesh.face_families.cell_b[on_boundary[cell_mesh.face_families.family]] == -1)


def test_bundle_cell_mesh_without_a_river_has_no_river_family() -> None:
    cell_mesh = cell_mesh_from_bundle(_square_bundle(river=False), crs_wkt=CRS)

    assert not cell_mesh.face_rows("rivers").any()
    assert cell_mesh.face_rows("boundary:west").any()


def test_bundle_cell_mesh_needs_triangles() -> None:
    bundle = _square_bundle()
    quad = SimpleNamespace(cell_id=0, node_indices=(0, 1, 7, 6))
    bundle = SimpleNamespace(nodes=bundle.nodes, cells=(quad,), edges=())

    with pytest.raises(ValueError, match="triangles"):
        cell_mesh_from_bundle(bundle, crs_wkt=CRS)
