"""The cell types of the mesh, their aliases and their sizes."""

from __future__ import annotations

import pytest

from hydromodpy.mesh.planar.cell_types import CellType

FIXED = {
    # cell type: nodes, dimension, meshio name
    CellType.TRIANGLE: (3, 2, "triangle"),
    CellType.QUADRILATERAL: (4, 2, "quad"),
    CellType.WEDGE: (6, 3, "wedge"),
    CellType.HEXAHEDRON: (8, 3, "hexahedron"),
}


KNOWN_NAMES = [
    ("triangle", CellType.TRIANGLE),
    ("quadrilateral", CellType.QUADRILATERAL),
    ("wedge", CellType.WEDGE),
    ("hexahedron", CellType.HEXAHEDRON),
    ("tri", CellType.TRIANGLE),
    ("quad", CellType.QUADRILATERAL),
    ("triangular_prism", CellType.WEDGE),
    ("hex", CellType.HEXAHEDRON),
    ("voronoi", CellType.POLYGON),
]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        *KNOWN_NAMES,
        ("TRIANGLE", CellType.TRIANGLE),
        ("  Quad  ", CellType.QUADRILATERAL),
    ],
)
def test_a_name_or_an_alias_gives_its_cell_type(name: str, expected: CellType) -> None:
    assert CellType.from_string(name) is expected


def test_an_unknown_name_raises_and_lists_the_names_it_knows() -> None:
    with pytest.raises(ValueError, match="Unknown cell type 'tetrahedron'") as error:
        CellType.from_string("tetrahedron")

    listed = str(error.value).split("Allowed: ", 1)[1].split(", ")
    assert {name for name, _ in KNOWN_NAMES} <= set(listed)
    assert all(isinstance(CellType.from_string(name), CellType) for name in listed)


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
