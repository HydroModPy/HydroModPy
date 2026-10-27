"""The cell types of the mesh, their aliases and their sizes."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.mesh.model.cell_types import CellType

FIXED = {
    # cell type: nodes, dimension, meshio name
    CellType.TRIANGLE: (3, 2, "triangle"),
    CellType.QUADRILATERAL: (4, 2, "quad"),
    CellType.WEDGE: (6, 3, "wedge"),
    CellType.HEXAHEDRON: (8, 3, "hexahedron"),
}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("triangle", CellType.TRIANGLE),
        ("quadrilateral", CellType.QUADRILATERAL),
        ("wedge", CellType.WEDGE),
        ("hexahedron", CellType.HEXAHEDRON),
        ("tri", CellType.TRIANGLE),
        ("quad", CellType.QUADRILATERAL),
        ("triangular_prism", CellType.WEDGE),
        ("hex", CellType.HEXAHEDRON),
        ("voronoi", CellType.POLYGON),
        ("TRIANGLE", CellType.TRIANGLE),
        ("  Quad  ", CellType.QUADRILATERAL),
    ],
)
def test_a_name_or_an_alias_gives_its_cell_type(name: str, expected: CellType) -> None:
    assert CellType.from_string(name) is expected


def test_an_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown cell type 'tetrahedron'"):
        CellType.from_string("tetrahedron")


@pytest.mark.parametrize("cell_type", list(FIXED), ids=lambda cell_type: cell_type.value)
def test_a_fixed_cell_type_gives_its_nodes_dimension_and_meshio_name(cell_type: CellType) -> None:
    nodes, dimension, meshio_name = FIXED[cell_type]

    assert cell_type.nodes_per_cell == nodes
    assert cell_type.dimension == dimension
    assert cell_type.meshio_name == meshio_name
    assert not cell_type.is_ragged


def test_a_polygon_is_planar_ragged_and_has_no_node_count() -> None:
    assert CellType.POLYGON.is_ragged
    assert CellType.POLYGON.dimension == 2
    assert CellType.POLYGON.meshio_name == "polygon"
    with pytest.raises(ValueError, match="variable node count"):
        _ = CellType.POLYGON.nodes_per_cell
