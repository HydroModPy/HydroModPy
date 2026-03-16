"""Tests for CellType enumeration."""

import pytest

from hydromodpy.mesh.cell_types import CellType


def test_from_string_canonical_names() -> None:
    assert CellType.from_string("triangle") is CellType.TRIANGLE
    assert CellType.from_string("quadrilateral") is CellType.QUADRILATERAL
    assert CellType.from_string("wedge") is CellType.WEDGE
    assert CellType.from_string("hexahedron") is CellType.HEXAHEDRON


def test_from_string_aliases() -> None:
    assert CellType.from_string("tri") is CellType.TRIANGLE
    assert CellType.from_string("quad") is CellType.QUADRILATERAL
    assert CellType.from_string("triangular_prism") is CellType.WEDGE
    assert CellType.from_string("hex") is CellType.HEXAHEDRON


def test_from_string_case_insensitive() -> None:
    assert CellType.from_string("TRIANGLE") is CellType.TRIANGLE
    assert CellType.from_string("  Quad  ") is CellType.QUADRILATERAL


def test_from_string_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown cell type"):
        CellType.from_string("tetrahedron")


def test_nodes_per_cell() -> None:
    assert CellType.TRIANGLE.nodes_per_cell == 3
    assert CellType.QUADRILATERAL.nodes_per_cell == 4
    assert CellType.WEDGE.nodes_per_cell == 6
    assert CellType.HEXAHEDRON.nodes_per_cell == 8


def test_dimension() -> None:
    assert CellType.TRIANGLE.dimension == 2
    assert CellType.QUADRILATERAL.dimension == 2
    assert CellType.WEDGE.dimension == 3
    assert CellType.HEXAHEDRON.dimension == 3


def test_meshio_name() -> None:
    assert CellType.TRIANGLE.meshio_name == "triangle"
    assert CellType.QUADRILATERAL.meshio_name == "quad"
    assert CellType.WEDGE.meshio_name == "wedge"
    assert CellType.HEXAHEDRON.meshio_name == "hexahedron"
