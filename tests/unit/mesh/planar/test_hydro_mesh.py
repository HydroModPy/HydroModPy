"""The HydroMesh container and its cell blocks."""

from __future__ import annotations

import re

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.mesh_cases import regular_mesh


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


POLYGON_VERTICES = np.array([[0, 0], [2, 0], [2, 2], [0, 2], [1, 3], [-1, 2]], dtype=float)
"""A quad (0, 1, 2, 3) and a triangle (3, 2, 4) sharing an edge, and one free node."""


def test_polygon_centroid_skips_padding() -> None:
    block = CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3]), np.array([3, 2, 4])))
    x, y = HydroMesh(vertices=POLYGON_VERTICES, cell_blocks=(block,)).cell_centroids()
    np.testing.assert_allclose(np.column_stack([x, y]), [[1.0, 1.0], [1.0, 7.0 / 3.0]])


def test_mixed_blocks_pad_with_minus_one() -> None:
    assert _mixed_mesh().flat_connectivity.tolist() == [[0, 1, 2, 3], [1, 4, 2, -1]]


def test_mixed_mesh_has_no_single_type() -> None:
    with pytest.raises(ValueError, match="mixed cell types"):
        _ = _mixed_mesh().single_cell_type


def test_summary_of_a_grid() -> None:
    mesh = regular_mesh(1, 2).mesh
    summary = mesh.as_summary()
    assert summary["ndim"] == 2
    assert summary["n_cells"] == 2
    assert summary["is_structured"] is True
    assert summary["cell_types"] == ["quadrilateral"]


def test_html_table_of_a_grid() -> None:
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


def test_html_table_of_a_mixed_mesh() -> None:
    rows = _html_rows(_mixed_mesh())

    assert rows["cell_types"] == "quadrilateral, triangle"
    assert rows["structured"] == "no"
    assert rows["structured_shape"] == rows["cell_data"] == rows["point_data"] == "&mdash;"


BLOCK_REFUSALS = [
    pytest.param(CellType.TRIANGLE, np.array([[0, 1, 2, 3]]), "triangle", id="row too wide"),
    pytest.param(
        CellType.POLYGON,
        (np.array([0, 1, 2]), np.array([0, 1])),
        ">= 3 node indices",
        id="polygon of two nodes",
    ),
    pytest.param(
        CellType.POLYGON,
        np.array([[0, 1, 2, 3], [3, -1, 2, 4]]),
        "nodes first, then -1 padding",
        id="hole in a row",
    ),
    pytest.param(
        CellType.POLYGON,
        np.array([[0, 1, 2, 3], [3, 2, 4, -2]]),
        "nodes first, then -1 padding",
        id="padding below -1",
    ),
    pytest.param(
        CellType.POLYGON,
        (np.array([0, 1, 2, -1]), np.array([0, 1, 2])),
        "outside vertices",
        id="padded node array",
    ),
    pytest.param(
        CellType.POLYGON,
        (np.array([0, -5, 2]), np.array([0, 1, 2])),
        "outside vertices",
        id="negative node id",
    ),
]

TWO_NODES = np.array([[0, 0], [1, 0]], dtype=float)
MESH_REFUSALS = [
    pytest.param(
        TWO_NODES,
        (CellBlock(CellType.TRIANGLE, np.array([[0, 1, 5]])),),
        "outside vertices",
        id="triangle past the vertices",
    ),
    pytest.param(
        TWO_NODES,
        (CellBlock(CellType.POLYGON, (np.array([0, 1, 5]),)),),
        "outside vertices",
        id="polygon past the vertices",
    ),
    pytest.param(TWO_NODES, (), "at least one block", id="no block"),
    pytest.param(
        np.arange(3, dtype=float).reshape(3, 1),
        (CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
        "n_nodes, 2|3",
        id="one column",
    ),
]


@pytest.mark.parametrize(("cell_type", "connectivity", "reason"), BLOCK_REFUSALS)
def test_block_refusals(cell_type, connectivity, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        CellBlock(cell_type, connectivity)


@pytest.mark.parametrize(("vertices", "blocks", "reason"), MESH_REFUSALS)
def test_mesh_refusals(vertices, blocks, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        HydroMesh(vertices=vertices, cell_blocks=blocks)


def test_data_size_refusals() -> None:
    mesh = _make_triangle_mesh()

    with pytest.raises(ValueError, match="2 values"):
        mesh.with_cell_data(k=np.array([1.0, 2.0, 3.0]))
    with pytest.raises(ValueError, match="point_data\\['z'\\] must have 4 values"):
        mesh.with_point_data(z=np.zeros(3))
