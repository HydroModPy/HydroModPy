"""``engine_id -> MeshEngine class``, and the surface a third party registers on.

The in-tree engines are declared once, in :data:`_BUILTIN_PATHS`, and imported on
first lookup, so resolving ``regular`` never imports gmsh. The
``hydromodpy.mesh.engine`` entry-point group is the out-of-tree surface. The lookup
rules (names, refusals, messages) live in
:class:`~hydromodpy.core.plugin_registry.PluginRegistry`. An unknown id raises
:class:`~hydromodpy.core.exceptions.MeshRequestError`.

Besides the port members, a mesh engine must declare a non-empty ``engine_version``
and a :class:`~hydromodpy.mesh.port.MeshEngineCapabilities`.

:func:`engine_accepted` is the one rule that says whether a reader, a solver
that lists the meshes it reads, reads the meshes of an engine. It lives here
because it may have to resolve the engine to read its capabilities.
"""

from __future__ import annotations

from collections.abc import Collection

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.mesh.port import (
    ANY_PLANAR_ENGINE,
    PLANAR_CELL_TYPES,
    MeshEngineCapabilities,
    engine_members,
)

ENTRY_POINT_GROUP = "hydromodpy.mesh.engine"
"""The out-of-tree plugin group. One entry point per engine, named on its id."""

DEFAULT_ENGINE_ID = "regular"
"""The engine a project without ``[mesh]`` gets: cells are the DEM pixels."""

_BUILTIN_PATHS: dict[str, str] = {
    "catchment": "hydromodpy.mesh.engines.catchment.engine:CatchmentMeshEngine",
    "regular": "hydromodpy.mesh.engines.regular.engine:RegularMeshEngine",
    "triangle": "hydromodpy.mesh.engines.triangle.engine:TriangleMeshEngine",
    "voronoi": "hydromodpy.mesh.engines.voronoi.engine:VoronoiMeshEngine",
}
"""Dotted ``"<module>:<class>"`` paths to the in-tree engines, imported on first lookup."""


def _check_version_and_capabilities(engine_cls: type) -> None:
    name = getattr(engine_cls, "__qualname__", engine_cls)
    version = getattr(engine_cls, "engine_version", None)
    if not isinstance(version, str) or not version.strip():
        raise TypeError(
            f"{name!r} declares engine_version={version!r}; a non-empty str is required."
        )
    capabilities = getattr(engine_cls, "capabilities", None)
    if not isinstance(capabilities, MeshEngineCapabilities):
        raise TypeError(
            f"{name!r} declares capabilities of type {type(capabilities).__name__}; "
            "a mesh engine declares a MeshEngineCapabilities."
        )


mesh_engines = PluginRegistry(
    kind="mesh engine",
    id_attributes=("engine_id",),
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=engine_members,
    default_id=DEFAULT_ENGINE_ID,
    error=MeshRequestError,
    validate=_check_version_and_capabilities,
)
"""The mesh-engine registry: ``mesh_engines.get``, ``names`` and ``register``."""


def engine_accepted(accepted: Collection[str], engine_id: str) -> bool:
    """Whether a reader that accepts *accepted* reads the meshes of *engine_id*.

    A reader names engine ids, or :data:`~hydromodpy.mesh.port.ANY_PLANAR_ENGINE`
    to read any engine whose cell types are planar ones and that is not lumped.
    The engine class is loaded only when the id is not named and the token is
    there, since only then do its capabilities decide. An id nothing serves
    raises :class:`~hydromodpy.core.exceptions.MeshRequestError` in that case.
    """
    if engine_id in accepted:
        return True
    if ANY_PLANAR_ENGINE not in accepted:
        return False
    capabilities = mesh_engines.get(engine_id).capabilities
    return not capabilities.lumped and set(capabilities.cell_types) <= PLANAR_CELL_TYPES


__all__ = [
    "DEFAULT_ENGINE_ID",
    "ENTRY_POINT_GROUP",
    "engine_accepted",
    "mesh_engines",
]
