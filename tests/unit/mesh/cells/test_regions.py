"""The cells split into regions once the faces of a family are cut.

``components_without`` cuts by cell pair and ``family_regions`` by edge. The
labels number the regions in the order of their first cell. Two cells that
share two edges tell the two rules apart: a cut pair splits them, while one cut
edge leaves them joined through the other.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.mesh.cells.regions import family_regions
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
