"""Topology-aware Grid Protocol for HydroModPy meshes.

A ``Grid`` is the read-only contract every spatial pivot exposes regardless of
whether the underlying simulation is structured (DIS), unstructured-in-plan
(DISV) or lumped (single-cell, GR4J). Concrete implementations live in
:mod:`hydromodpy.spatial.mesh.grid_wrappers`.

The literal :data:`GridTopology` mirrors the canonical values stored in the
catalog ``simulations.mesh_topology`` column and read back by
:class:`hydromodpy.results.run.Run`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.hydro_mesh import HydroMesh


GridTopology = Literal["regular", "irregular", "lumped"]


@runtime_checkable
class Grid(Protocol):
    """Topology-aware view over a HydroModPy spatial grid.

    The protocol is intentionally minimal: implementations are free to add
    domain-specific fields, but every consumer can rely on these attributes
    being present.
    """

    @property
    def topology(self) -> GridTopology: ...

    @property
    def n_cells(self) -> int: ...

    @property
    def n_layers(self) -> int: ...

    @property
    def crs(self) -> str | None: ...

    @property
    def bbox(self) -> tuple[float, float, float, float]: ...

    def to_hydro_mesh(self) -> HydroMesh:
        """Return a :class:`HydroMesh` representation, or raise for lumped."""
        ...


__all__ = ("Grid", "GridTopology")
