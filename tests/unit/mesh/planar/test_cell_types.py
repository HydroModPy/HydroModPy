"""The cell types of the mesh, their aliases and their sizes."""

from __future__ import annotations

import pytest

from hydromodpy.mesh.planar.cell_types import CellType

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


def test_an_unknown_name_raises_and_lists_the_names_it_knows() -> None:
    with pytest.raises(ValueError, match="Unknown cell type 'tetrahedron'") as error:
        CellType.from_string("tetrahedron")

    listed = str(error.value).split("Allowed: ", 1)[1].split(", ")
    assert {name for name, _ in KNOWN_NAMES} <= set(listed)
    assert all(isinstance(CellType.from_string(name), CellType) for name in listed)


def test_a_polygon_is_planar_ragged_and_has_no_node_count() -> None:
    assert CellType.POLYGON.is_ragged
    assert CellType.POLYGON.dimension == 2
    assert CellType.POLYGON.meshio_name == "polygon"
    with pytest.raises(ValueError, match="variable node count"):
        _ = CellType.POLYGON.nodes_per_cell
