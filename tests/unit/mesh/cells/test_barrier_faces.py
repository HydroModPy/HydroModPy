"""Map a barrier line onto the mesh faces it separates (a continuous cut).

A cutoff wall is barred on the shared faces whose two cells the trace passes
BETWEEN (the segment joining their centers is crossed), so the barrier is a
single connected fence with no leak paths, independent of the grid. The centers
are those of the cell mesh. On a mesh whose faces follow the line (exact faces
and a ``barriers`` family) the wall takes the family faces on the line, and the
faces it crosses where no family face covers it.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from hydromodpy.mesh.cells.barrier_faces import barrier_edges, barrier_faces_from_line
from hydromodpy.mesh.planar.planar_cell_mesh import (
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.mesh.request import BARRIER_FAMILY
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import regular_mesh

DECLARATIONS = {"graded": False, "exact_faces": False, "deterministic": True, "needs_cache": False}


def _quad_grid(ncol: int, nrow: int) -> PlanarCellMesh:
    """``ncol`` by ``nrow`` unit cells on [0, ncol] x [0, nrow]; row 0 is north."""
    return regular_mesh(nrow, ncol)


def test_one_cell_has_no_face() -> None:
    assert barrier_faces_from_line(_quad_grid(1, 1), LineString([(0.5, -1.0), (0.5, 2.0)])) == []


# A mesh whose faces follow its lines: 4 columns and 3 rows of 10 m cells, row 0 north.
# The faces x = 20, between columns 1 and 2, join node (row, 2) to node (row + 1, 2).


def _x20_face(row: int) -> tuple[int, int, int, int]:
    """Cells and nodes of the face x = 20 of one row."""
    return row * 4 + 1, row * 4 + 2, row * 5 + 2, (row + 1) * 5 + 2


def _followed(family: str, rows: tuple[int, ...]) -> PlanarCellMesh:
    """The grid declared exact, with *family* on the x = 20 faces of *rows*."""
    grid = regular_mesh(3, 4, dx=10.0)
    faces = [_x20_face(row) for row in rows]
    table = FaceFamilyTable(
        names=(family,),
        family=np.zeros(len(faces)),
        cell_a=[face[0] for face in faces],
        cell_b=[face[1] for face in faces],
        node_a=[face[2] for face in faces],
        node_b=[face[3] for face in faces],
        zone_left=np.full(len(faces), -1),
        zone_right=np.full(len(faces), -1),
    )
    return build_planar_cell_mesh(
        grid.mesh,
        grid.centers,
        center_kind="cell_center",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={**DECLARATIONS, "exact_faces": True},
        face_families=table,
        structured_shape=(3, 4),
    )


def _x20_edges(cell_mesh: PlanarCellMesh, rows: tuple[int, ...]) -> list[int]:
    pairs = cell_mesh.geometry.edge_cells.tolist()
    return sorted(pairs.index([_x20_face(row)[0], _x20_face(row)[1]]) for row in rows)


def test_line_past_followed_faces() -> None:
    # The family covers the two northern faces; the line runs on south to y = 0.
    cell_mesh = _followed(BARRIER_FAMILY, rows=(0, 1))

    rows = barrier_edges(cell_mesh, LineString([(20.0, 30.0), (20.0, 0.0)]))

    assert rows.tolist() == _x20_edges(cell_mesh, (0, 1, 2))


def test_other_family_faces_ignored() -> None:
    cell_mesh = _followed("lakes", rows=(0, 1, 2))
    line = LineString([(15.0, 30.0), (35.0, 0.0)])

    np.testing.assert_array_equal(
        barrier_edges(cell_mesh, line), barrier_edges(regular_mesh(3, 4, dx=10.0), line)
    )
