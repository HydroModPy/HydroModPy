"""``engine_id -> TerrainEngine class``, and the surface a third party registers on.

Why it arrives only now, and what changed
-----------------------------------------
``spatial/terrain/__init__.py`` refused this module on purpose: a selection
point that resolves a name nobody outside this repository can supply is
decoration, which is D34. The refusal named its own condition -- "it arrives
with the capability that has to choose one" -- and that capability is
``terrain-delineate``, delivered by F4c. Its ``request.json`` now carries the
name, so a third party selects an engine this repository does not name, from
outside, without a patch.

That is the canonical test of G1. Until this module existed, three production
sites imported ``WhiteboxTerrainEngine`` and constructed it by name --
``geographic/core/flow_products.py``, ``geographic/core/catchment_from_point.py``
and ``site_selection/hydrology/worker.py`` -- so "replace WhiteboxTools without
touching the callers" was not hard, it was impossible.

No ``[project.entry-points]`` table, and that is D21
----------------------------------------------------
The group is the **out-of-tree** surface only. The two engines of this tree are
declared once, in :data:`_BUILTIN_PATHS`, and importing one is deferred to the
first lookup that asks for it -- so resolving ``numpy_d8`` pulls in neither
``whitebox_workflows`` nor the facade behind it. Declaring them in
``pyproject.toml`` as well would give each one a second name and a second source
of truth.

Why a class and why binding by parameter name
---------------------------------------------
:func:`get` returns the class and :func:`create` builds it, binding only the
constructor parameters the class names -- the rule
:func:`hydromodpy.data.source.registry.build_from_section` already uses. It is
what lets the resolution stay ignorant of what a Whitebox facade is:
``WhiteboxTerrainEngine`` declares ``backend``, so the shared facade handle the
geographic chain carries reaches it; ``NumpyTerrainEngine`` declares none, so
the same call builds it with nothing. Neither the caller nor the registry has to
know which engine wants what.

What is refused
---------------
- **A class that does not satisfy the port** is refused by :func:`register`,
  naming the members. The list comes from the port's own
  :func:`~hydromodpy.spatial.terrain.port.engine_members`, so it never drifts
  from the Protocol, and a member bound to ``None`` counts as missing -- that
  one passes ``hasattr`` and fails the first call.
- **An entry point whose name is not the ``engine_id`` its class declares** is
  refused. The name is what a request writes and the ``engine_id`` is what the
  provenance of a sealed job is stamped with; two words for one engine is how a
  request and its record start describing different things.
- **A plugin that takes a name this build ships** is refused, for the reason the
  data-source registry gives: a published capability description that names
  ``whitebox_workflows`` would describe something else entirely.
"""

from __future__ import annotations

import importlib
import inspect
from importlib.metadata import entry_points

from hydromodpy.core.exceptions import TerrainRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.terrain.port import engine_members

logger = get_logger(__name__)

ENTRY_POINT_GROUP = "hydromodpy.terrain.engine"
"""The out-of-tree plugin group. One entry point per engine, named on its id."""

DEFAULT_ENGINE_ID = "whitebox_workflows"
"""The engine a caller that names none gets.

It is the one every number in this repository was produced with. The two engines
shipped here are substitutable, not equivalent -- measured on
``DEM_gouville_25m.tif`` they disagree by a factor 2.5 on a catchment area --
so the default is a compatibility statement, not a preference.
"""

_BUILTIN_PATHS: dict[str, str] = {
    "numpy_d8": "hydromodpy.spatial.terrain.numpy_engine:NumpyTerrainEngine",
    "whitebox_workflows": "hydromodpy.spatial.terrain.whitebox_engine:WhiteboxTerrainEngine",
}
"""Dotted paths to the in-tree engine classes, imported on first lookup.

Format ``"<module>:<class>"``, the one the solver and data-source registries
already use, so the three plugin surfaces of this repository read the same way.
"""

_REGISTRY: dict[str, type] = {}
_PLUGINS_LOADED = False


def builtin_engine_ids() -> tuple[str, ...]:
    """Return the ids this build ships, sorted, plugins excluded.

    Separate from :func:`list_engine_ids` because the two answer different
    questions. What a build **describes** is frozen package data; what a
    deployment **resolves** depends on what is installed beside it.
    """
    return tuple(sorted(_BUILTIN_PATHS))


def list_engine_ids() -> tuple[str, ...]:
    """Return every id resolvable here, built-in and installed, sorted.

    Loads the plugin group, because the answer is wrong without it. Does not
    import a built-in: the paths are the declaration, and the class behind one
    is only needed when somebody asks for it by name.
    """
    if not _PLUGINS_LOADED:
        load_plugins()
    return tuple(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS)))


def is_registered(engine_id: str) -> bool:
    """Whether :func:`get` would resolve *engine_id* without raising."""
    return engine_id in list_engine_ids()


def register(engine_cls: type, *, replace: bool = False) -> type:
    """Register an engine class under the ``engine_id`` it declares.

    The id is read **off the class** and never passed in: a registration that
    could name the class something else is a registration that lets a sealed
    job's provenance and the request that asked for it disagree.

    Returns the class unchanged, so it can be used as a decorator.

    Raises
    ------
    TypeError
        When the class declares no usable ``engine_id``, or lacks one of the
        members :class:`~hydromodpy.spatial.terrain.port.TerrainEngine` requires.
    ValueError
        When the id is already taken and *replace* is not set.
    """
    engine_id = getattr(engine_cls, "engine_id", None)
    if not isinstance(engine_id, str) or not engine_id.strip():
        raise TypeError(
            f"{_name_of(engine_cls)!r} declares engine_id={engine_id!r} on the class, and a "
            "registry keyed on a name cannot hold an engine that has none. It is a "
            "ClassVar[str] in the port; a value computed per instance is not readable here."
        )
    missing = _unusable_members(engine_cls)
    if missing:
        raise TypeError(
            f"{_name_of(engine_cls)!r} cannot serve {engine_id!r}: it does not satisfy the "
            f"terrain port, missing or unusable {', '.join(missing)}. A chain that conditions "
            "a DEM and then delineates calls every one of them, so the gap surfaces mid-job "
            "rather than here."
        )
    if engine_id in _REGISTRY and not replace:
        raise ValueError(
            f"A terrain engine is already registered for {engine_id!r}: "
            f"{_name_of(_REGISTRY[engine_id])}. Pass replace=True to substitute it."
        )
    _REGISTRY[engine_id] = engine_cls
    return engine_cls


def get(engine_id: str | None = None) -> type:
    """Return the engine **class** registered under *engine_id*.

    ``None`` resolves :data:`DEFAULT_ENGINE_ID`, so a caller with nothing to say
    about the engine says nothing. Resolution order is the cache, then the
    in-tree declaration, then one scan of the plugin group: nothing is imported
    until a lookup needs it.

    Raises
    ------
    TerrainRequestError
        When no engine answers to that name. A malformed request and not an
        engine failure: the caller fixes it without a DEM in hand.
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
    raise TerrainRequestError(
        f"No terrain engine is registered for {wanted!r}. This installation serves {known}. "
        f"A third-party engine joins that list through the {ENTRY_POINT_GROUP!r} "
        "entry-point group, without a patch to HydroModPy."
    )


def create(engine_id: str | None = None, **options: object) -> object:
    """Build the engine registered under *engine_id*, binding what it names.

    Only the constructor parameters the class declares are bound, and every
    keyword a parameter can reach is -- keyword-only and positional-or-keyword
    alike. An option no engine parameter names never arrives, which is what
    keeps the caller from having to know that ``backend`` means something to the
    Whitebox engine and nothing to the numpy one.

    Restricting this to keyword-only parameters was rejected for the reason
    D-level precedent already gives on the data-source side: both in-tree
    engines happen to declare theirs positionally-or-keyword, so the narrower
    rule would pass every gate here while silently dropping the value of a
    third-party engine that spelled its parameter the same way.

    Raises
    ------
    TerrainRequestError
        From :func:`get`, when no engine answers to that name; or when the
        constructor demands a positional-only argument, which a keyword cannot
        fill.
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
        raise TerrainRequestError(
            f"Engine {getattr(engine_cls, 'engine_id', engine_cls)!r} takes "
            f"{', '.join(unfillable)} positionally only, and it is built from named options. "
            "Declare them as keyword parameters."
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
    warning naming what is wrong with it, never raised: one broken plugin must
    not take down a host that asked for a different engine.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        declared = tuple(entry_points(group=ENTRY_POINT_GROUP))
    except Exception as exc:
        # The scan itself, not one entry point: unreadable or contradictory
        # distribution metadata takes down ``importlib.metadata`` for every
        # group at once, and a host that asked for a built-in must not be taken
        # down by a distribution it never named.
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
            logger.warning("terrain engine plugin %r ignored: its entry-point name is empty.", name)
            continue
        if name in _BUILTIN_PATHS:
            logger.warning(
                "terrain engine plugin %r ignored: %r is an engine this build ships and "
                "names in the description of terrain-delineate. Answering under that name "
                "would make a published, byte-gated document describe a different engine.",
                entry_point,
                name,
            )
            continue
        if name in _REGISTRY and not force:
            continue
        try:
            engine_cls = entry_point.load()
        except Exception as exc:  # pragma: no cover - exercised with stub entry points
            logger.warning("failed to load terrain engine plugin %r: %s", entry_point, exc)
            continue
        if getattr(engine_cls, "engine_id", None) != name:
            logger.warning(
                "terrain engine plugin %r ignored: the entry-point name is %r while the class "
                "declares engine_id=%r. The name is what a request writes and the engine_id is "
                "what a sealed job is stamped with; two words for one engine is how the two "
                "start describing different things.",
                entry_point,
                name,
                getattr(engine_cls, "engine_id", None),
            )
            continue
        try:
            register(engine_cls, replace=force)
        except (TypeError, ValueError) as exc:
            logger.warning("terrain engine plugin %r ignored: %s", entry_point, exc)
            continue
        count += 1
    _PLUGINS_LOADED = True
    return count


def unregister(engine_id: str) -> None:
    """Drop one entry, built-in declaration included. Primarily for tests.

    The declaration goes too, otherwise the next :func:`get` lazy-loads the
    built-in straight back and the removal looks like it did nothing. A fixture
    that removes a built-in restores both mappings.
    """
    _REGISTRY.pop(engine_id, None)
    _BUILTIN_PATHS.pop(engine_id, None)


def _load_builtin(engine_id: str) -> type | None:
    """Import and register the in-tree class for *engine_id*, if there is one.

    An id this build declares and cannot load is still an id this installation
    does not serve, so it leaves through :func:`get`'s own exception with the
    reason attached. ``whitebox_workflows`` is the live case: the distribution
    is an optional extra, and without it the class raises at import time.
    """
    path = _BUILTIN_PATHS.get(engine_id)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    try:
        module = importlib.import_module(module_path)
        engine_cls = getattr(module, class_name)
    except Exception as exc:
        # Deliberately every exception and not ``ImportError``: a module that
        # fails at import time fails in whatever way its own imports do, and a
        # C extension refusing to initialise raises none of them.
        raise TerrainRequestError(
            f"{engine_id!r} is declared by this build at {path!r} and cannot be loaded here: "
            f"{type(exc).__name__}: {exc}. The declaration is right and the installation is "
            "not, so this is fixed by repairing the environment, not by editing the request."
        ) from exc
    return register(engine_cls, replace=True)


def _unusable_members(engine_cls: type) -> tuple[str, ...]:
    """Return the port members *engine_cls* has no usable value for.

    Wider than :func:`~hydromodpy.spatial.terrain.port.missing_engine_members`,
    which answers presence only and says so: a member bound to ``None`` passes
    ``hasattr`` and fails the first call. A registry decides what gets built, so
    it is the place where "declared but unusable" has to be refused.
    """
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
