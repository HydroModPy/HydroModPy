"""The cells split into regions once the faces of a family are cut.

``components_without`` cuts by cell pair and ``family_regions`` by edge. The
labels number the regions in the order of their first cell. Two cells that
share two edges tell the two rules apart: a cut pair splits them, while one cut
edge leaves them joined through the other.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.mesh.cells.regions import components_without, family_regions
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import (
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import regular_mesh

DECLARATIONS = {"graded": False, "exact_faces": True, "deterministic": True, "needs_cache": False}


def _with_family(
    mesh: HydroMesh, centers: np.ndarray, faces: list[tuple[int, int, int, int]]
) -> PlanarCellMesh:
    """The cell mesh of *mesh* with the faces ``(cell_a, cell_b, node_a, node_b)`` in ``lakes``."""
    table = FaceFamilyTable(
        names=("lakes",),
        family=np.zeros(len(faces)),
        cell_a=[face[0] for face in faces],
        cell_b=[face[1] for face in faces],
        node_a=[face[2] for face in faces],
        node_b=[face[3] for face in faces],
        zone_left=np.full(len(faces), -1),
        zone_right=np.full(len(faces), -1),
    )
    return build_planar_cell_mesh(
        mesh,
        centers,
        center_kind="vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations=DECLARATIONS,
        face_families=table,
    )


def _x20_face(row: int) -> tuple[int, int, int, int]:
    """Cells and nodes of the face x = 20 of one row of the 4 x 3 grid of 10 m cells."""
    return row * 4 + 1, row * 4 + 2, row * 5 + 2, (row + 1) * 5 + 2


def _grid_with_x20_faces(rows: tuple[int, ...], *extra: tuple[int, int, int, int]):
    grid = regular_mesh(3, 4, dx=10.0)
    faces = [_x20_face(row) for row in rows] + list(extra)
    return _with_family(grid.mesh, grid.centers, faces)


def _two_cells_on_two_edges() -> HydroMesh:
    """Pentagons 0 and 1 share the edges (1, 2) and (2, 3) on x = 1; quad 2 lies east of 1."""
    vertices = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 0.5],
            [1.0, 1.0],
            [0.0, 1.0],
            [2.0, 0.0],
            [2.0, 1.0],
            [3.0, 0.0],
            [3.0, 1.0],
        ]
    )
    cells = (np.array([0, 1, 2, 3, 4]), np.array([1, 5, 6, 3, 2]), np.array([5, 7, 8, 6]))
    return HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))


def _vertex_means(mesh: HydroMesh) -> np.ndarray:
    return np.column_stack(mesh.cell_centroids())


def test_a_mesh_without_the_family_is_one_region() -> None:
    grid = regular_mesh(3, 4, dx=10.0)

    labels = family_regions(grid, "lakes")

    assert labels.dtype == np.int64
    assert labels.tolist() == [0] * grid.n_cells


def test_a_family_across_the_grid_splits_it_in_the_order_of_the_first_cells() -> None:
    labels = family_regions(_grid_with_x20_faces((0, 1, 2)), "lakes")

    assert labels.dtype == np.int64
    assert labels.tolist() == [0, 0, 1, 1] * 3


def test_a_family_with_a_gap_leaves_one_region() -> None:
    assert family_regions(_grid_with_x20_faces((0, 1)), "lakes").tolist() == [0] * 12


def test_a_family_row_on_two_nodes_no_edge_joins_cuts_nothing() -> None:
    # Nodes 0 and 6 are the corners of a diagonal of cell 0.
    cell_mesh = _grid_with_x20_faces((0, 1), (0, 1, 0, 6))

    assert family_regions(cell_mesh, "lakes").tolist() == [0] * 12


def test_cut_pairs_split_in_either_order_and_boundary_rows_cut_nothing() -> None:
    geometry = regular_mesh(3, 4, dx=10.0).geometry
    cut_a = np.array([1, 6, 9, 0])
    cut_b = np.array([2, 5, 10, -1])

    labels = components_without(geometry, cut_a, cut_b)

    assert labels.dtype == np.int32
    assert labels.tolist() == [0, 0, 1, 1] * 3


def test_no_cut_pair_leaves_one_component() -> None:
    geometry = regular_mesh(2, 2).geometry
    none = np.empty(0, dtype=np.int64)

    assert components_without(geometry, none, none).tolist() == [0] * 4


def test_a_cut_pair_splits_two_cells_that_share_two_edges() -> None:
    cell_mesh = _with_family(
        _two_cells_on_two_edges(), _vertex_means(_two_cells_on_two_edges()), []
    )

    labels = components_without(cell_mesh.geometry, np.array([0]), np.array([1]))

    assert labels.tolist() == [0, 1, 1]


def test_one_cut_edge_of_two_shared_edges_keeps_the_two_cells_in_one_region() -> None:
    mesh = _two_cells_on_two_edges()
    one_edge = _with_family(mesh, _vertex_means(mesh), [(0, 1, 1, 2)])
    both_edges = _with_family(mesh, _vertex_means(mesh), [(0, 1, 1, 2), (0, 1, 2, 3)])

    assert family_regions(one_edge, "lakes").tolist() == [0, 0, 0]
    assert family_regions(both_edges, "lakes").tolist() == [0, 1, 1]
