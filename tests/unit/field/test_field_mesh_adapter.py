"""The HydroMesh of a field mesh, and the field mesh a consumer samples a HydroMesh on."""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib.tri as mtri
import numpy as np
import pytest

from hydromodpy.spatial.field.meshes import StructuredFieldMesh
from hydromodpy.spatial.field.meshes.field_mesh_adapter import (
    from_field_mesh,
    from_gmsh_planar,
    to_field_mesh,
)
from hydromodpy.spatial.field.meshes.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.spatial.field.meshes.polygon_field_mesh import PolygonFieldMesh
from hydromodpy.spatial.field.meshes.triangular_field_mesh import TriangularUnstructuredFieldMesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

_VERTICES = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.0]])


def _two_polygon_mesh() -> HydroMesh:
    """A left pentagon and a right quad sharing the edge (1, 0)-(1, 1), with their seeds."""
    verts = np.array(
        [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [-0.3, 0.5], [0.0, 0.0], [2.0, 0.0], [2.0, 1.0]],
        dtype=float,
    )
    left = np.array([0, 1, 2, 3, 4])
    right = np.array([0, 5, 6, 1])
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=(left, right)),),
        cell_data={"disv_cell_center": np.array([[0.3, 0.5], [1.5, 0.5]], dtype=float)},
    )


def test_a_gmsh_like_triangle_becomes_a_hydro_mesh() -> None:
    planar = SimpleNamespace(
        points_xy=np.array([[0, 0], [1, 0], [0.5, 1]], dtype=float),
        connectivity=np.array([[0, 1, 2]], dtype=int),
        cell_type="triangle",
    )
    mesh = from_gmsh_planar(planar)
    assert mesh.ndim == 2
    assert mesh.n_cells == 1
    assert mesh.single_cell_type is CellType.TRIANGLE


def test_a_structured_field_mesh_keeps_its_shape() -> None:
    x, y = np.meshgrid([0, 1, 2], [0, 1])
    mesh = from_field_mesh(StructuredFieldMesh(x_plot=x, y_plot=y))
    assert mesh.is_structured
    assert mesh.structured_shape == (1, 2)
    assert mesh.n_cells == 2


def test_a_gmsh_planar_field_mesh_is_read_from_its_points() -> None:
    planar = GmshPlanarMesh2D(
        points_xy=_VERTICES, connectivity=[[0, 1, 2], [0, 2, 3]], cell_type="triangle"
    )

    mesh = from_field_mesh(planar)

    np.testing.assert_array_equal(mesh.vertices, _VERTICES)
    assert mesh.flat_connectivity.tolist() == [[0, 1, 2], [0, 2, 3]]


def test_an_unstructured_triangle_field_mesh_has_no_grid_shape() -> None:
    x, y = _VERTICES[:, 0], _VERTICES[:, 1]
    field_mesh = TriangularUnstructuredFieldMesh(
        x_plot=x, y_plot=y, triangulation=mtri.Triangulation(x, y, [[0, 1, 2], [0, 2, 3]])
    )

    mesh = from_field_mesh(field_mesh)

    assert mesh.structured_shape is None
    assert mesh.single_cell_type is CellType.TRIANGLE
    assert mesh.n_cells == 2


def test_a_field_mesh_without_cells_raises() -> None:
    empty = SimpleNamespace(x_plot=np.zeros(3), y_plot=np.zeros(3), cells=())

    with pytest.raises(ValueError, match="field_mesh has no cells"):
        from_field_mesh(empty)


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


def test_ragged_polygons_keep_their_arity_and_their_seeds() -> None:
    mesh = _two_polygon_mesh()

    field_mesh = to_field_mesh(mesh)

    assert isinstance(field_mesh, PolygonFieldMesh)
    assert [len(cell.node_indices) for cell in field_mesh.iter_cells()] == [5, 4]
    xc, yc = field_mesh.cell_centroids()
    np.testing.assert_allclose(np.c_[xc, yc], mesh.cell_data["disv_cell_center"])
    assert field_mesh.to_cell_values(np.array([1.0, 2.0])).tolist() == [1.0, 2.0]
