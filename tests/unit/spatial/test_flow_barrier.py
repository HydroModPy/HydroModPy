"""Map a barrier line onto the planar-mesh faces it crosses."""

from __future__ import annotations

import numpy as np
import pytest
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


def test_trace_collinear_with_a_mesh_edge_raises() -> None:
    mesh = _row_of_quads()
    # A trace running along the shared face x = 1 is geometrically ambiguous.
    with pytest.raises(ValueError, match="collinear"):
        barrier_faces_from_line(mesh, LineString([(1.0, 0.0), (1.0, 1.0)]))


def test_zigzag_crossing_the_same_face_twice_keeps_the_face_once() -> None:
    mesh = _row_of_quads()
    # Re-crosses the x = 1 face (MultiPoint intersection); the face must survive.
    faces = barrier_faces_from_line(mesh, LineString([(0.5, 0.2), (1.5, 0.5), (0.5, 0.8)]))
    assert [(f.cell_a, f.cell_b) for f in faces] == [(0, 1)]


def test_line_ending_on_a_face_is_not_a_barrier() -> None:
    mesh = _row_of_quads()
    # Stops on the x = 1 face without entering cell 1: a touch, not a crossing.
    assert barrier_faces_from_line(mesh, LineString([(0.5, 0.5), (1.0, 0.5)])) == []
