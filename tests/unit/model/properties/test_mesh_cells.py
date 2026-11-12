"""The cells a support field samples, read from a planar cell mesh."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.model.properties.mesh_cells import (
    MeshWithValues,
    cell_mesh_from_edges,
    cell_values,
    mesh_cells,
)
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.field_cases import planar_mesh

_VERTICES = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.0]])


def test_ragged_polygons_keep_their_arity_their_seeds_and_one_value_each() -> None:
    """A left pentagon and a right quad share the edge (1, 0)-(1, 1)."""
    verts = [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [-0.3, 0.5], [0.0, 0.0], [2.0, 0.0], [2.0, 1.0]]
    centers = np.array([[0.3, 0.5], [1.5, 0.5]])
    cell_mesh = planar_mesh(
        verts, [[0, 1, 2, 3, 4], [0, 5, 6, 1]], CellType.POLYGON, centers=centers
    )

    cells = mesh_cells(cell_mesh)
    carried = MeshWithValues(mesh=cell_mesh, cell_values=np.array([1.0, 2.0]), label="k")

    assert [cell.kind for cell in cells] == ["polygon", "polygon"]
    assert [cell.node_indices for cell in cells] == [(0, 1, 2, 3, 4), (0, 5, 6, 1)]
    assert [cell.vertices.shape for cell in cells] == [(5, 2), (4, 2)]
    np.testing.assert_array_equal([cell.centroid for cell in cells], cell_mesh.centers)
    assert cell_values(cell_mesh, np.array([[1.0], [2.0]])).tolist() == [1.0, 2.0]
    with pytest.raises(ValueError, match="exactly one value per cell: got 3 for 2 cells"):
        cell_values(cell_mesh, np.array([1.0, 2.0, 3.0]))
    assert (carried.n_cells, carried.label) == (2, "k")


@pytest.mark.parametrize(
    ("x_edges", "y_edges", "reason"),
    [([0.0], [0.0, 1.0], "at least 2 values"), ([0.0, 1.0], [1.0, 0.0], "strictly increasing")],
    ids=["one edge", "decreasing edges"],
)
def test_a_grid_of_edges_needs_increasing_edges(x_edges, y_edges, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        cell_mesh_from_edges(x_edges, y_edges, crs_wkt=TEST_CRS_WKT)
