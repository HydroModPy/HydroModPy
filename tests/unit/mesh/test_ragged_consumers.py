"""Ragged-polygon safety of the mesh consumers touched by the Voronoi migration."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from hydromodpy.spatial.field.meshes.polygon_field_mesh import PolygonFieldMesh
from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.flow_barrier import barrier_faces_from_line
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.mesh_orthogonality import connection_nonorthogonality_deg


def _two_polygon_mesh() -> HydroMesh:
    # Two cells sharing the vertical edge (1,0)-(1,1): a left pentagon and a right
    # quad, so the block is genuinely ragged (5 and 4 nodes).
    verts = np.array(
        [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [-0.3, 0.5], [0.0, 0.0], [2.0, 0.0], [2.0, 1.0]],
        dtype=float,
    )
    left = np.array([0, 1, 2, 3, 4])  # pentagon
    right = np.array([0, 5, 6, 1])  # quad
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=(left, right)),),
        cell_data={"disv_cell_center": np.array([[0.3, 0.5], [1.5, 0.5]], dtype=float)},
    )


def test_flow_barrier_faces_on_a_ragged_mesh() -> None:
    mesh = _two_polygon_mesh()
    line = LineString([(1.0, -0.5), (1.0, 1.5)])  # passes between cells 0 and 1 (crosses their
    faces = barrier_faces_from_line(mesh, line)  # centroid segment) -> bars the shared face
    assert len(faces) == 1
    assert {faces[0].cell_a, faces[0].cell_b} == {0, 1}


def test_mesh_orthogonality_uses_seed_centers_on_a_ragged_mesh() -> None:
    mesh = _two_polygon_mesh()
    angles = connection_nonorthogonality_deg(mesh)
    # One interior connection; seeds (0.3,0.5)-(1.5,0.5) are horizontal, the shared
    # face is vertical, so the connection is perpendicular (~0 deg).
    assert angles.shape == (1,)
    assert angles[0] < 1e-6


def test_polygon_field_mesh_iterates_ragged_cells() -> None:
    mesh = _two_polygon_mesh()
    fm = PolygonFieldMesh(mesh)
    assert fm.n_cells == 2
    cells = list(fm.iter_cells())
    assert [len(c.node_indices) for c in cells] == [5, 4]  # ragged arity preserved
    xc, yc = fm.cell_centroids()
    assert np.allclose(np.c_[xc, yc], mesh.cell_data["disv_cell_center"])  # seed centers
    vals = fm.to_cell_values(np.array([1.0, 2.0]))
    assert list(vals) == [1.0, 2.0]
