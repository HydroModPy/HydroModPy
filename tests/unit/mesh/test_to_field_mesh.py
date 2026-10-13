"""The field mesh a consumer samples a field on is built from a planar HydroMesh."""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.field.meshes.polygon_field_mesh import PolygonFieldMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import to_field_mesh
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

_VERTICES = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.0]])


def test_triangles_are_sampled_as_triangles() -> None:
    mesh = HydroMesh(
        vertices=_VERTICES,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]])),),
    )

    field_mesh = to_field_mesh(mesh)

    assert isinstance(field_mesh, GmshPlanarMesh2D)
    assert {cell.kind for cell in field_mesh.cells} == {"triangle"}
    np.testing.assert_array_equal(field_mesh.cell_centroids(), mesh.cell_centroids())


def test_quadrilaterals_keep_their_kind() -> None:
    mesh = HydroMesh(
        vertices=_VERTICES,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, np.array([[0, 1, 2, 3]])),),
    )

    assert {cell.kind for cell in to_field_mesh(mesh).cells} == {"quadrilateral"}


def test_polygons_are_sampled_by_area() -> None:
    polygons = (np.array([0, 1, 2, 3]), np.array([0, 2, 3]))
    mesh = HydroMesh(
        vertices=_VERTICES,
        cell_blocks=(CellBlock(CellType.POLYGON, polygons),),
    )

    field_mesh = to_field_mesh(mesh)

    assert isinstance(field_mesh, PolygonFieldMesh)
    assert field_mesh.n_cells == 2
