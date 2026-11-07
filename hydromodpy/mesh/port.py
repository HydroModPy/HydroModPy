"""The mesh port: what a mesh engine owes its callers.

An engine is a class with three ``ClassVar`` members and one method. It reads a
:class:`~hydromodpy.mesh.request.MeshRequest` and returns a
``PlanarCellMesh``; it reads no file and no config. A third-party engine imports
this module, the request module, the planar cell mesh model and
:mod:`hydromodpy.core.exceptions`, and nothing else from HydroModPy.

The capabilities are declarations a caller can act on before building: a solver
lists the engines it reads (``accepted_meshes``), the workflow caches what an
engine cannot rebuild bit for bit (``needs_cache``), and the QA reports what the
engine claims (``graded``, ``exact_faces``, ``deterministic``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, get_args, runtime_checkable

from hydromodpy.mesh.planar.cell_types import CellType

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.mesh.request import MeshRequest

__all__ = [
    "ANY_PLANAR_ENGINE",
    "PLANAR_CELL_TYPES",
    "CellFamilyRule",
    "MeshEngine",
    "MeshEngineCapabilities",
    "engine_accepted",
    "engine_members",
    "missing_engine_members",
]

CellFamilyRule = Literal["exact", "rasterized", "derived_from_faces"]
"""How an engine forms a cell family: on the line, by rasterizing it, or from its faces."""

PLANAR_CELL_TYPES: frozenset[CellType] = frozenset(
    {CellType.TRIANGLE, CellType.QUADRILATERAL, CellType.POLYGON}
)
"""The cell types a planar cell mesh may hold."""

ANY_PLANAR_ENGINE = "*planar"
"""Token of ``accepted_meshes``: any engine whose cells are planar cell types."""


@dataclass(frozen=True)
class MeshEngineCapabilities:
    """What an engine declares about every mesh it builds."""

    cell_types: tuple[CellType, ...]
    structured: bool
    graded: bool
    exact_faces: bool
    cell_families: CellFamilyRule
    deterministic: bool
    needs_cache: bool

    def __post_init__(self) -> None:
        """Refuse a cell type outside the planar ones and an unknown family rule."""
        cell_types = tuple(CellType(cell_type) for cell_type in self.cell_types)
        if not cell_types or not set(cell_types) <= PLANAR_CELL_TYPES:
            raise ValueError(
                f"cell_types must be a non-empty subset of {sorted(t.value for t in PLANAR_CELL_TYPES)}"
            )
        object.__setattr__(self, "cell_types", cell_types)
        if self.cell_families not in get_args(CellFamilyRule):
            raise ValueError(
                f"cell_families must be one of {get_args(CellFamilyRule)}, got {self.cell_families!r}"
            )
        for name in ("structured", "graded", "exact_faces", "deterministic", "needs_cache"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"MeshEngineCapabilities.{name} must be a bool")

    def declarations(self) -> dict[str, bool]:
        """The four claims the QA of every mesh of this engine reports."""
        return {
            "graded": self.graded,
            "exact_faces": self.exact_faces,
            "deterministic": self.deterministic,
            "needs_cache": self.needs_cache,
        }


@runtime_checkable
class MeshEngine(Protocol):
    """One engine turns a mesh request into a planar cell mesh.

    Engines conform structurally: no base class. ``engine_version`` changes
    whenever the mesh the engine returns for one request changes, since the
    mesh cache keys on it. An engine that cannot honor a request raises
    :class:`~hydromodpy.core.exceptions.MeshRequestError` naming what it refuses.
    """

    engine_id: ClassVar[str]
    engine_version: ClassVar[str]
    capabilities: ClassVar[MeshEngineCapabilities]

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Build the planar cell mesh *request* asks for."""
        ...


def engine_accepted(
    accepted: Collection[str], engine_id: str, capabilities: MeshEngineCapabilities
) -> bool:
    """Whether a reader that accepts *accepted* reads the meshes of *engine_id*.

    A reader names engine ids, or :data:`ANY_PLANAR_ENGINE` to read any engine
    whose cell types are planar ones.
    """
    if engine_id in accepted:
        return True
    return ANY_PLANAR_ENGINE in accepted and set(capabilities.cell_types) <= PLANAR_CELL_TYPES


def engine_members() -> tuple[str, ...]:
    """Return the member names :class:`MeshEngine` requires, derived from the Protocol."""
    annotated = set(MeshEngine.__annotations__)
    defined = {
        name
        for name, value in vars(MeshEngine).items()
        if callable(value) and not name.startswith("_")
    }
    return tuple(sorted(annotated | defined))


def missing_engine_members(candidate: object) -> tuple[str, ...]:
    """Return the members *candidate* has no attribute for (presence only)."""
    return tuple(name for name in engine_members() if not hasattr(candidate, name))
