"""``engine_id -> MeshEngine class``, and the surface a third party registers on.

The in-tree engines are declared once, in :data:`_BUILTIN_PATHS`, and imported on
first lookup, so resolving ``regular`` never imports gmsh. The
``hydromodpy.mesh.engine`` entry-point group is the out-of-tree surface. The lookup
rules (names, refusals, messages) live in
:class:`~hydromodpy.core.plugin_registry.PluginRegistry`. An unknown id raises
:class:`~hydromodpy.core.exceptions.MeshRequestError`.

Besides the port members, a mesh engine must declare a non-empty ``engine_version``
and a :class:`~hydromodpy.mesh.port.MeshEngineCapabilities`.
"""

from __future__ import annotations

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.mesh.port import MeshEngineCapabilities, engine_members

ENTRY_POINT_GROUP = "hydromodpy.mesh.engine"
"""The out-of-tree plugin group. One entry point per engine, named on its id."""

DEFAULT_ENGINE_ID = "regular"
"""The engine a project without ``[mesh]`` gets: cells are the DEM pixels."""

_BUILTIN_PATHS: dict[str, str] = {
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

__all__ = [
    "DEFAULT_ENGINE_ID",
    "ENTRY_POINT_GROUP",
    "mesh_engines",
]
