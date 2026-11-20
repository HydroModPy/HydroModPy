"""``engine_id -> TerrainEngine class``, and the surface a third party registers on.

``[geographic] terrain_engine`` carries the engine name, and this module resolves
it, so a third party selects an engine this repository does not name, from
outside, without a patch. No caller constructs ``WhiteboxTerrainEngine`` by name,
and WhiteboxTools can be replaced without touching them.

The two engines of this tree are declared once, in :data:`_BUILTIN_PATHS`, and
imported on the first lookup that asks for one, so resolving ``numpy_d8`` pulls in
neither ``whitebox_workflows`` nor the facade behind it. The
``hydromodpy.terrain.engine`` entry-point group is the out-of-tree surface only.
The lookup rules (names, refusals, messages, binding of the constructor
parameters by name) live in :class:`~hydromodpy.core.plugin_registry.PluginRegistry`.
An unknown id is a malformed request and raises
:class:`~hydromodpy.core.exceptions.TerrainRequestError`.
"""

from __future__ import annotations

from hydromodpy.catchment.terrain.port import engine_members
from hydromodpy.core.exceptions import TerrainRequestError
from hydromodpy.core.plugin_registry import PluginRegistry

ENTRY_POINT_GROUP = "hydromodpy.terrain.engine"
"""The out-of-tree plugin group. One entry point per engine, named on its id."""

DEFAULT_ENGINE_ID = "whitebox_workflows"
"""The engine a caller that names none gets.

It is the one every number in this repository was produced with. The two engines
shipped here are substitutable, not equivalent (measured on
``DEM_gouville_25m.tif`` they disagree by a factor 2.5 on a catchment area), so
the default is a compatibility statement, not a preference.
"""

_BUILTIN_PATHS: dict[str, str] = {
    "numpy_d8": "hydromodpy.catchment.terrain.numpy_engine:NumpyTerrainEngine",
    "whitebox_workflows": "hydromodpy.catchment.terrain.whitebox_engine:WhiteboxTerrainEngine",
}
"""Dotted ``"<module>:<class>"`` paths to the in-tree engines, imported on first lookup."""

terrain_engines = PluginRegistry(
    kind="terrain engine",
    id_attributes=("engine_id",),
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=engine_members,
    default_id=DEFAULT_ENGINE_ID,
    error=TerrainRequestError,
)
"""The terrain-engine registry: ``terrain_engines.get``, ``names`` and ``register``."""

__all__ = [
    "DEFAULT_ENGINE_ID",
    "ENTRY_POINT_GROUP",
    "terrain_engines",
]
