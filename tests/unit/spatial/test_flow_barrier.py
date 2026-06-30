"""Map a barrier line onto the planar-mesh faces it crosses."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.flow_barrier import barrier_faces_from_line
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


def _row_of_quads() -> HydroMesh:
    # Three unit quads in a row sharing vertical faces at x = 1 and x = 2.
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    return HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))


def test_line_crossing_both_interior_faces() -> None:
    mesh = _row_of_quads()
    faces = barrier_faces_from_line(mesh, LineString([(0.5, 0.5), (2.5, 0.5)]))
    assert [(f.cell_a, f.cell_b) for f in faces] == [(0, 1), (1, 2)]
    # ordered by line position
    assert faces[0].s < faces[1].s
    assert faces[0].s == 0.25
    assert faces[1].s == 0.75


def test_partial_line_crosses_one_face() -> None:
    mesh = _row_of_quads()
    faces = barrier_faces_from_line(mesh, LineString([(0.5, 0.5), (1.5, 0.5)]))
    assert [(f.cell_a, f.cell_b) for f in faces] == [(0, 1)]


def test_line_missing_all_interior_faces() -> None:
    mesh = _row_of_quads()
    # A line entirely inside one cell crosses no shared face.
    assert barrier_faces_from_line(mesh, LineString([(0.2, 0.2), (0.8, 0.8)])) == []
