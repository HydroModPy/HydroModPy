"""``engine_id -> MeshEngine class``, and the surface a third party registers on.

Same rules as :mod:`hydromodpy.spatial.terrain.registry`:

- the in-tree engines are declared once, in :data:`_BUILTIN_PATHS`, and imported
  on first lookup, so resolving ``regular`` never imports gmsh;
- the ``hydromodpy.mesh.engine`` entry-point group is the out-of-tree surface;
  an entry point must be named on the ``engine_id`` its class declares, and a
  name this build ships is refused;
- a class that does not satisfy the port, or whose capabilities are not a
  :class:`~hydromodpy.spatial.mesh.port.MeshEngineCapabilities`, is refused by
  :func:`register`;
- an unknown id raises :class:`~hydromodpy.core.exceptions.MeshRequestError`
  naming what this installation serves.
"""

from __future__ import annotations

import importlib
import inspect
from importlib.metadata import entry_points

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities, engine_members

logger = get_logger(__name__)

ENTRY_POINT_GROUP = "hydromodpy.mesh.engine"
"""The out-of-tree plugin group. One entry point per engine, named on its id."""

DEFAULT_ENGINE_ID = "regular"
"""The engine a project without ``[mesh]`` gets: cells are the DEM pixels."""

_BUILTIN_PATHS: dict[str, str] = {
    "regular": "hydromodpy.spatial.mesh.engines.regular.engine:RegularMeshEngine",
    "triangle": "hydromodpy.spatial.mesh.engines.triangle.engine:TriangleMeshEngine",
    "voronoi": "hydromodpy.spatial.mesh.engines.voronoi.engine:VoronoiMeshEngine",
}
"""Dotted ``"<module>:<class>"`` paths to the in-tree engines, imported on first lookup."""

_REGISTRY: dict[str, type] = {}
_PLUGINS_LOADED = False


def builtin_engine_ids() -> tuple[str, ...]:
    """Return the ids this build ships, sorted, plugins excluded."""
    return tuple(sorted(_BUILTIN_PATHS))


def list_engine_ids() -> tuple[str, ...]:
    """Return every id resolvable here, built-in and installed, sorted.

    Loads the plugin group; imports no built-in.
    """
    if not _PLUGINS_LOADED:
        load_plugins()
    return tuple(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS)))


def is_registered(engine_id: str) -> bool:
    """Whether :func:`get` would find a declaration for *engine_id*."""
    return engine_id in list_engine_ids()


def register(engine_cls: type, *, replace: bool = False) -> type:
    """Register an engine class under the ``engine_id`` it declares.

    Returns the class unchanged, so it can be used as a decorator.

    Raises
    ------
    TypeError
        When the class declares no usable ``engine_id`` or ``engine_version``,
        lacks a member of :class:`~hydromodpy.spatial.mesh.port.MeshEngine`, or
        declares capabilities of another type.
    ValueError
        When the id is already taken and *replace* is not set.
    """
    name = _name_of(engine_cls)
    engine_id = getattr(engine_cls, "engine_id", None)
    if not isinstance(engine_id, str) or not engine_id.strip():
        raise TypeError(
            f"{name!r} declares engine_id={engine_id!r}; a mesh engine declares a non-empty "
            "ClassVar[str] engine_id on the class."
        )
    missing = _unusable_members(engine_cls)
    if missing:
        raise TypeError(
            f"{name!r} cannot serve {engine_id!r}: it does not satisfy the mesh port, "
            f"missing or unusable {', '.join(missing)}."
        )
    version = engine_cls.engine_version
    if not isinstance(version, str) or not version.strip():
        raise TypeError(
            f"{name!r} declares engine_version={version!r}; a non-empty str is required."
        )
    if not isinstance(engine_cls.capabilities, MeshEngineCapabilities):
        raise TypeError(
            f"{name!r} declares capabilities of type {type(engine_cls.capabilities).__name__}; "
            "a mesh engine declares a MeshEngineCapabilities."
        )
    if engine_id in _REGISTRY and not replace:
        raise ValueError(
            f"A mesh engine is already registered for {engine_id!r}: "
            f"{_name_of(_REGISTRY[engine_id])}. Pass replace=True to substitute it."
        )
    _REGISTRY[engine_id] = engine_cls
    return engine_cls


def get(engine_id: str | None = None) -> type:
    """Return the engine **class** registered under *engine_id*.

    ``None`` resolves :data:`DEFAULT_ENGINE_ID`. Resolution order: the cache,
    the in-tree declaration, then one scan of the plugin group.

    Raises
    ------
    MeshRequestError
        When no engine answers to that name, or a declared built-in cannot be
        imported here.
    """
    wanted = DEFAULT_ENGINE_ID if engine_id is None else engine_id
    cls = _REGISTRY.get(wanted)
    if cls is not None:
        return cls
    cls = _load_builtin(wanted)
    if cls is not None:
        return cls
    if not _PLUGINS_LOADED:
        load_plugins()
        cls = _REGISTRY.get(wanted)
        if cls is not None:
            return cls
    known = ", ".join(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS))) or "none"
    raise MeshRequestError(
        f"No mesh engine is registered for {wanted!r}. This installation serves {known}. "
        f"A third-party engine joins that list through the {ENTRY_POINT_GROUP!r} "
        "entry-point group, without a patch to HydroModPy."
    )


def create(engine_id: str | None = None, **options: object) -> object:
    """Build the engine registered under *engine_id*, binding the options it names.

    Only constructor parameters the class declares are bound; an option no
    parameter names never arrives.

    Raises
    ------
    MeshRequestError
        From :func:`get`, or when the constructor demands a positional-only
        argument.
    """
    engine_cls = get(engine_id)
    parameters = inspect.signature(engine_cls).parameters
    unfillable = [
        name
        for name, parameter in parameters.items()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        and parameter.default is inspect.Parameter.empty
    ]
    if unfillable:
        raise MeshRequestError(
            f"Mesh engine {engine_cls.engine_id!r} takes {', '.join(unfillable)} positionally "
            "only, and it is built from named options. Declare them as keyword parameters."
        )
    bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    arguments = {
        name: options[name]
        for name, parameter in parameters.items()
        if parameter.kind in bindable and name in options
    }
    return engine_cls(**arguments)


def load_plugins(*, force: bool = False) -> int:
    """Register every conforming engine declared in the entry-point group.

    Returns the number newly registered. A bad entry point is skipped with a
    warning naming what is wrong with it: one broken plugin must not take down
    a host that asked for another engine.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        declared = tuple(entry_points(group=ENTRY_POINT_GROUP))
    except Exception as exc:
        # Unreadable distribution metadata breaks the scan of every group; a host
        # that asked for a built-in must not fail on a distribution it never named.
        logger.warning(
            "the %r entry-point group could not be scanned, so no plugin is registered: %s",
            ENTRY_POINT_GROUP,
            exc,
        )
        _PLUGINS_LOADED = True
        return 0
    for entry_point in declared:
        name = str(entry_point.name).strip()
        if not name:
            logger.warning(
                "mesh engine plugin %r ignored: its entry-point name is empty.", entry_point
            )
            continue
        if name in _BUILTIN_PATHS:
            logger.warning(
                "mesh engine plugin %r ignored: %r is an engine this build ships.",
                entry_point,
                name,
            )
            continue
        if name in _REGISTRY and not force:
            continue
        try:
            engine_cls = entry_point.load()
        except Exception as exc:  # pragma: no cover - exercised with stub entry points
            logger.warning("failed to load mesh engine plugin %r: %s", entry_point, exc)
            continue
        if getattr(engine_cls, "engine_id", None) != name:
            logger.warning(
                "mesh engine plugin %r ignored: the entry-point name is %r while the class "
                "declares engine_id=%r; a config names the first and a mesh records the second.",
                entry_point,
                name,
                getattr(engine_cls, "engine_id", None),
            )
            continue
        try:
            register(engine_cls, replace=force)
        except (TypeError, ValueError) as exc:
            logger.warning("mesh engine plugin %r ignored: %s", entry_point, exc)
            continue
        count += 1
    _PLUGINS_LOADED = True
    return count


def unregister(engine_id: str) -> None:
    """Drop one entry, built-in declaration included. Primarily for tests."""
    _REGISTRY.pop(engine_id, None)
    _BUILTIN_PATHS.pop(engine_id, None)


def _load_builtin(engine_id: str) -> type | None:
    """Import and register the in-tree class for *engine_id*, if there is one."""
    path = _BUILTIN_PATHS.get(engine_id)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    try:
        module = importlib.import_module(module_path)
        engine_cls = getattr(module, class_name)
    except Exception as exc:
        # Every exception: a module failing at import time fails the way its own
        # imports do, and a C extension refusing to load raises no ImportError.
        raise MeshRequestError(
            f"{engine_id!r} is declared by this build at {path!r} and cannot be loaded here: "
            f"{type(exc).__name__}: {exc}."
        ) from exc
    return register(engine_cls, replace=True)


def _unusable_members(engine_cls: type) -> tuple[str, ...]:
    """Return the port members *engine_cls* has no usable value for (``None`` counts)."""
    return tuple(name for name in engine_members() if getattr(engine_cls, name, None) is None)


def _name_of(candidate: object) -> str:
    return str(getattr(candidate, "__qualname__", candidate))


__all__ = [
    "DEFAULT_ENGINE_ID",
    "ENTRY_POINT_GROUP",
    "builtin_engine_ids",
    "create",
    "get",
    "is_registered",
    "list_engine_ids",
    "load_plugins",
    "register",
    "unregister",
]
