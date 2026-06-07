"""Canonical cell-type enumeration for the unified mesh pivot.

Every mesh representation in HydroModPy (structured grids, gmsh triangular
meshes, extruded prisms) maps to one of these cell types.  The enum is the
single source of truth for cell-type naming across the codebase.
"""

from __future__ import annotations

from enum import Enum


class CellType(Enum):
    """Supported cell geometries."""

    # -- 2D -------------------------------------------------------------------
    TRIANGLE = "triangle"
    QUADRILATERAL = "quadrilateral"

    # -- 3D (layered extrusion) -----------------------------------------------
    WEDGE = "wedge"  # triangular prism (3 + 3 nodes)
    HEXAHEDRON = "hexahedron"  # quadrilateral prism (4 + 4 nodes)

    @property
    def nodes_per_cell(self) -> int:
        return _NODES_PER_CELL[self]

    @property
    def dimension(self) -> int:
        return 3 if self in _3D_TYPES else 2

    @property
    def meshio_name(self) -> str:
        return _MESHIO_NAMES[self]

    @classmethod
    def from_string(cls, name: str) -> CellType:
        """Resolve a cell type from any common alias."""
        key = str(name).strip().lower()
        result = _ALIASES.get(key)
        if result is None:
            allowed = ", ".join(sorted(_ALIASES))
            raise ValueError(f"Unknown cell type '{name}'. Allowed: {allowed}")
        return result


_NODES_PER_CELL = {
    CellType.TRIANGLE: 3,
    CellType.QUADRILATERAL: 4,
    CellType.WEDGE: 6,
    CellType.HEXAHEDRON: 8,
}

_3D_TYPES = {CellType.WEDGE, CellType.HEXAHEDRON}

_MESHIO_NAMES = {
    CellType.TRIANGLE: "triangle",
    CellType.QUADRILATERAL: "quad",
    CellType.WEDGE: "wedge",
    CellType.HEXAHEDRON: "hexahedron",
}

_ALIASES: dict[str, CellType] = {
    "triangle": CellType.TRIANGLE,
    "triangles": CellType.TRIANGLE,
    "tri": CellType.TRIANGLE,
    "quadrilateral": CellType.QUADRILATERAL,
    "quadrilaterals": CellType.QUADRILATERAL,
    "quad": CellType.QUADRILATERAL,
    "quads": CellType.QUADRILATERAL,
    "wedge": CellType.WEDGE,
    "triangular_prism": CellType.WEDGE,
    "hexahedron": CellType.HEXAHEDRON,
    "quadrilateral_prism": CellType.HEXAHEDRON,
    "hex": CellType.HEXAHEDRON,
}
