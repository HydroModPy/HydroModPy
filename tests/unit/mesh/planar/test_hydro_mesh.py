"""The HydroMesh container and its cell blocks."""

from __future__ import annotations

import re

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.mesh_cases import regular_mesh

WEDGE_VERTICES = np.array(
    [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
)


def _make_triangle_mesh() -> HydroMesh:
    vertices = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
    conn = np.array([[0, 1, 2], [1, 3, 2]], dtype=int)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
    )


def _mixed_mesh() -> HydroMesh:
    """A triangle block and a quadrilateral block on one set of nodes."""
    vertices = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0]], dtype=float)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(CellType.QUADRILATERAL, [[0, 1, 2, 3]]),
            CellBlock(CellType.TRIANGLE, [[1, 4, 2]]),
        ),
    )


def _html_rows(mesh: HydroMesh) -> dict[str, str]:
    return dict(re.findall(r"<th[^>]*>(\w+)</th><td>(.*?)</td>", mesh._repr_html_()))


def test_a_block_whose_rows_do_not_fit_its_cell_type_raises() -> None:
    with pytest.raises(ValueError, match="triangle"):
        CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2, 3]], dtype=int))


def test_a_polygon_of_two_nodes_raises() -> None:
    with pytest.raises(ValueError, match=">= 3 node indices"):
        CellBlock(CellType.POLYGON, (np.array([0, 1, 2]), np.array([0, 1])))


POLYGON_VERTICES = np.array([[0, 0], [2, 0], [2, 2], [0, 2], [1, 3], [-1, 2]], dtype=float)
"""A quad (0, 1, 2, 3) and a triangle (3, 2, 4) sharing an edge, and one free node."""


@pytest.mark.parametrize(
    "rows", [[[0, 1, 2, 3], [3, -1, 2, 4]], [[0, 1, 2, 3], [3, 2, 4, -2]]], ids=["hole", "below -1"]
)
def test_a_polygon_row_with_a_free_slot_before_a_node_raises(rows: list[list[int]]) -> None:
    with pytest.raises(ValueError, match="nodes first, then -1 padding"):
        CellBlock(cell_type=CellType.POLYGON, connectivity=np.array(rows))


def test_the_vertex_mean_of_a_polygon_skips_its_padding() -> None:
    block = CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3]), np.array([3, 2, 4])))
    x, y = HydroMesh(vertices=POLYGON_VERTICES, cell_blocks=(block,)).cell_centroids()
    np.testing.assert_allclose(np.column_stack([x, y]), [[1.0, 1.0], [1.0, 7.0 / 3.0]])


def test_blocks_of_two_widths_stack_into_one_table_padded_with_minus_one() -> None:
    assert _mixed_mesh().flat_connectivity.tolist() == [[0, 1, 2, 3], [1, 4, 2, -1]]


def test_a_mesh_of_two_cell_types_has_no_single_cell_type() -> None:
    with pytest.raises(ValueError, match="mixed cell types"):
        _ = _mixed_mesh().single_cell_type


def test_cell_data_of_the_wrong_size_raises() -> None:
    with pytest.raises(ValueError, match="2 values"):
        _make_triangle_mesh().with_cell_data(k=np.array([1.0, 2.0, 3.0]))


def test_point_data_of_the_wrong_size_raises() -> None:
    with pytest.raises(ValueError, match="point_data\\['z'\\] must have 4 values"):
        _make_triangle_mesh().with_point_data(z=np.zeros(3))


def test_a_mesh_without_a_block_raises() -> None:
    with pytest.raises(ValueError, match="at least one block"):
        HydroMesh(vertices=np.array([[0, 0]], dtype=float), cell_blocks=())


def test_vertices_of_one_column_raise() -> None:
    with pytest.raises(ValueError, match="n_nodes, 2|3"):
        HydroMesh(
            vertices=np.array([0, 1, 2], dtype=float).reshape(3, 1),
            cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
        )


@pytest.mark.parametrize(
    "block",
    [
        CellBlock(CellType.TRIANGLE, np.array([[0, 1, 5]])),
        CellBlock(CellType.POLYGON, (np.array([0, 1, 5]),)),
    ],
    ids=["triangle", "polygon"],
)
def test_a_node_id_past_the_vertices_raises(block: CellBlock) -> None:
    with pytest.raises(ValueError, match="outside vertices"):
        HydroMesh(vertices=np.array([[0, 0], [1, 0]], dtype=float), cell_blocks=(block,))


@pytest.mark.parametrize("cell", [[0, 1, 2, -1], [0, -5, 2]], ids=["minus one", "below"])
def test_a_negative_node_id_in_a_polygon_node_array_raises(cell: list[int]) -> None:
    with pytest.raises(ValueError, match="outside vertices"):
        CellBlock(CellType.POLYGON, (np.array(cell), np.array([0, 1, 2])))


def test_the_summary_names_the_grid() -> None:
    mesh = regular_mesh(1, 2).mesh
    summary = mesh.as_summary()
    assert summary["ndim"] == 2
    assert summary["n_cells"] == 2
    assert summary["is_structured"] is True
    assert summary["cell_types"] == ["quadrilateral"]


def test_the_notebook_table_of_a_grid_shows_its_shape_and_its_fields() -> None:
    mesh = regular_mesh(40, 30, dx=25.0).mesh
    mesh = mesh.with_cell_data(k=np.ones(mesh.n_cells)).with_point_data(z=np.zeros(mesh.n_nodes))

    rows = _html_rows(mesh)

    assert rows["n_cells"] == f"{mesh.n_cells:,}" == "1,200"
    assert rows["n_nodes"] == f"{mesh.n_nodes:,}"
    assert rows["cell_types"] == "quadrilateral"
    assert rows["structured"] == "yes"
    assert rows["structured_shape"] == str(mesh.structured_shape)
    assert rows["bounds"] == ", ".join(f"{b:.3g}" for b in mesh.bounds())
    assert rows["cell_data"] == "k"
    assert rows["point_data"] == "z"


def test_the_notebook_table_of_a_mixed_mesh_marks_what_it_lacks() -> None:
    rows = _html_rows(_mixed_mesh())

    assert rows["cell_types"] == "quadrilateral, triangle"
    assert rows["structured"] == "no"
    assert rows["structured_shape"] == rows["cell_data"] == rows["point_data"] == "&mdash;"
