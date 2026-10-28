"""The cells a support field samples, read from a planar cell mesh."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.field.mesh_cells import (
    MeshWithValues,
    cell_mesh_from_edges,
    cell_values,
    mesh_cells,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.field_cases import planar_mesh

_VERTICES = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.0]])


def _two_polygon_mesh():
    """A left pentagon and a right quad sharing the edge (1, 0)-(1, 1), with their seeds."""
    verts = [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [-0.3, 0.5], [0.0, 0.0], [2.0, 0.0], [2.0, 1.0]]
    cells = [[0, 1, 2, 3, 4], [0, 5, 6, 1]]
    return planar_mesh(verts, cells, CellType.POLYGON, centers=np.array([[0.3, 0.5], [1.5, 0.5]]))


def test_triangles_are_read_as_triangles_with_their_nodes_in_order() -> None:
    cell_mesh = planar_mesh(
        _VERTICES,
        [[0, 1, 2], [0, 2, 3]],
        CellType.TRIANGLE,
        centers=np.array([[1.3, 1.0], [0.7, 2.0]]),
    )

    cells = mesh_cells(cell_mesh)

    assert [cell.kind for cell in cells] == ["triangle", "triangle"]
    assert [cell.index for cell in cells] == [0, 1]
    assert cells[1].node_indices == (0, 2, 3)
    np.testing.assert_array_equal(cells[1].vertices, _VERTICES[[0, 2, 3]])
    assert cells[1].centroid == (0.7, 2.0)


def test_quadrilaterals_keep_their_kind() -> None:
    (cell,) = mesh_cells(planar_mesh(_VERTICES, [[0, 1, 2, 3]], CellType.QUADRILATERAL))

    assert cell.kind == "quadrilateral"
    np.testing.assert_array_equal(cell.vertices, _VERTICES)


def test_ragged_polygons_keep_their_arity_and_their_seeds() -> None:
    cell_mesh = _two_polygon_mesh()

    cells = mesh_cells(cell_mesh)

    assert [cell.kind for cell in cells] == ["polygon", "polygon"]
    assert [cell.node_indices for cell in cells] == [(0, 1, 2, 3, 4), (0, 5, 6, 1)]
    assert [cell.vertices.shape for cell in cells] == [(5, 2), (4, 2)]
    np.testing.assert_array_equal([cell.centroid for cell in cells], cell_mesh.centers)


def test_cell_values_are_one_value_per_cell() -> None:
    cell_mesh = _two_polygon_mesh()

    assert cell_values(cell_mesh, np.array([[1.0], [2.0]])).tolist() == [1.0, 2.0]
    with pytest.raises(ValueError, match="exactly one value per cell: got 3 for 2 cells"):
        cell_values(cell_mesh, np.array([1.0, 2.0, 3.0]))


def test_a_mesh_with_values_counts_the_cells_of_its_mesh() -> None:
    cell_mesh = _two_polygon_mesh()

    carried = MeshWithValues(mesh=cell_mesh, cell_values=np.array([1.0, 2.0]), label="k")

    assert carried.n_cells == 2
    assert carried.label == "k"


def test_a_grid_of_edges_runs_from_the_south_west_corner() -> None:
    cell_mesh = cell_mesh_from_edges([10.0, 20.0, 40.0], [30.0, 50.0], crs_wkt=TEST_CRS_WKT)

    cells = mesh_cells(cell_mesh)

    assert cell_mesh.structured_shape is None
    assert [cell.kind for cell in cells] == ["quadrilateral", "quadrilateral"]
    np.testing.assert_array_equal(cells[1].vertices, [[20, 30], [40, 30], [40, 50], [20, 50]])
    np.testing.assert_array_equal(cell_mesh.centers, [[15.0, 40.0], [30.0, 40.0]])


@pytest.mark.parametrize(
    ("x_edges", "y_edges", "reason"),
    [
        ([0.0], [0.0, 1.0], "at least 2 values"),
        ([0.0, 1.0], [1.0, 0.0], "strictly increasing"),
    ],
    ids=["one edge", "decreasing edges"],
)
def test_a_grid_of_edges_needs_increasing_edges(x_edges, y_edges, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        cell_mesh_from_edges(x_edges, y_edges, crs_wkt=TEST_CRS_WKT)
