"""Single ``(process_type, solver_name) → adapter class`` registry.

This module is the canonical merge of the historical registries that used to
live in ``solver/compatibility`` (class-based) and ``simulation/adapters``
(instance-based). It now serves both consumers:

- Adapter authors register their **class** here (or via the
  ``hydromodpy.solver`` entry-points group, see :func:`load_plugins`).
- The simulation runner asks for an **instance** through
  :func:`get_solver_adapter`, which instantiates the registered class on
  demand. This matches the lifecycle intent of ``SolverAdapter`` (one adapter
  = one run) while preserving the lightweight semantics of a static catalog.

The module also tracks **output extractors** keyed on the same
``(process_type, solver_name)`` pair. Extractors parse raw solver outputs
into the ``Catalog`` after a run completes.

Built-in adapters and extractors shipped in-tree are declared as dotted
paths and imported lazily on first lookup. That keeps
``hydromodpy.simulation`` free of eager imports of ``hydromodpy.solver``
concrete backends at package-load time.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.protocol import SolverAdapter

logger = get_logger(__name__)

AdapterKey = tuple[str, str]
Capabilities = frozenset[str]
ENTRY_POINT_GROUP = "hydromodpy.solver"
EXTRACTOR_ENTRY_POINT_GROUP = "hydromodpy.solver.extractor"

_REGISTRY: dict[AdapterKey, type] = {}
_EXTRACTOR_REGISTRY: dict[AdapterKey, type] = {}
_PLUGINS_LOADED = False
_EXTRACTOR_PLUGINS_LOADED = False

# Dotted paths to in-tree adapter classes. Loaded lazily by :func:`get` on
# first lookup so that importing this module (and therefore the whole
# ``hydromodpy.simulation`` stack) does not pull every solver backend.
# Format: ``"<module>:<class>"``.
_BUILTIN_PATHS: dict[AdapterKey, str] = {
    ("flow", "modflow_nwt"): "hydromodpy.solver.modflow_nwt.adapters.flow:ModflowNwtFlowAdapter",
    ("flow", "modflow6"): "hydromodpy.solver.modflow6.adapters.flow:Modflow6FlowAdapter",
    ("flow", "boussinesq"): "hydromodpy.solver.boussinesq.adapters.flow:BoussinesqFlowAdapter",
    (
        "transport",
        "modpath",
    ): "hydromodpy.solver.modflow_nwt.adapters.transport_modpath:ModpathTransportAdapter",
    (
        "transport",
        "mt3dms",
    ): "hydromodpy.solver.modflow_nwt.adapters.transport_mt3dms:Mt3dmsTransportAdapter",
    (
        "transport",
        "modflow6",
    ): "hydromodpy.solver.modflow6.adapters.transport:Modflow6GwtTransportAdapter",
    (
        "transport",
        "modflow6_prt",
    ): "hydromodpy.solver.modflow6.adapters.prt:Modflow6PrtTransportAdapter",
}

_BUILTIN_CAPABILITIES: dict[AdapterKey, Capabilities] = {
    ("flow", "modflow_nwt"): frozenset({"flow", "flow:heads", "flow:budget"}),
    ("flow", "modflow6"): frozenset({"flow", "flow:heads", "flow:budget"}),
    ("flow", "boussinesq"): frozenset({"flow", "flow:heads"}),
    ("transport", "modpath"): frozenset({"transport", "transport:particles"}),
    ("transport", "mt3dms"): frozenset({"transport", "transport:concentration"}),
    ("transport", "modflow6"): frozenset({"transport", "transport:concentration"}),
    ("transport", "modflow6_prt"): frozenset({"transport", "transport:particles"}),
}

# Dotted paths to in-tree output extractor classes. Keyed on the same
# ``(process_type, solver_name)`` pair as adapters so a solver code can
# carry one extractor per process (e.g. flow vs transport for MODFLOW 6).
_BUILTIN_EXTRACTOR_PATHS: dict[AdapterKey, str] = {
    (
        "flow",
        "modflow_nwt",
    ): "hydromodpy.solver.modflow_nwt.extractors.flow:ModflowNwtOutputAdapter",
    ("flow", "modflow6"): "hydromodpy.solver.modflow6.extractors.flow:Modflow6OutputAdapter",
    ("flow", "boussinesq"): "hydromodpy.solver.boussinesq.extractors.flow:BoussinesqOutputAdapter",
    ("transport", "mt3dms"): "hydromodpy.solver.modflow_nwt.extractors.mt3dms:Mt3dmsOutputAdapter",
    (
        "transport",
        "modflow6",
    ): "hydromodpy.solver.modflow6.extractors.transport:Modflow6GwtOutputAdapter",
    (
        "transport",
        "modflow6_prt",
    ): "hydromodpy.solver.modflow6.extractors.prt:Modflow6PrtOutputAdapter",
    (
        "transport",
        "modpath",
    ): "hydromodpy.solver.modflow_nwt.extractors.modpath:ModpathOutputAdapter",
}


def _load_builtin(key: AdapterKey) -> type | None:
    """Import and register the built-in adapter for *key*, if any.

    Returns the adapter class on success, ``None`` when *key* is not a
    known built-in. Idempotent: a second call short-circuits via the main
    ``_REGISTRY`` cache.
    """
    path = _BUILTIN_PATHS.get(key)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    _REGISTRY[key] = cls
    return cls


def _load_builtin_extractor(key: AdapterKey) -> type | None:
    """Import and register the built-in extractor for *key*, if any."""
    path = _BUILTIN_EXTRACTOR_PATHS.get(key)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    _EXTRACTOR_REGISTRY[key] = cls
    return cls


def register(
    process_type: str,
    solver_name: str,
    adapter_cls: type,
    *,
    replace: bool = False,
) -> type:
    """Register an adapter class for a ``(process_type, solver_name)`` pair.

    Returns the class unchanged so the function can be used as a decorator.
    """
    key = (process_type, solver_name)
    if key in _REGISTRY and not replace:
        raise ValueError(f"Solver adapter already registered for {process_type}/{solver_name}.")
    _REGISTRY[key] = adapter_cls
    return adapter_cls


def register_extractor(
    process_type: str,
    solver_name: str,
    extractor_cls: type,
    *,
    replace: bool = False,
) -> type:
    """Register an extractor class for a ``(process_type, solver_name)`` pair.

    Returns the class unchanged so it can be used as a decorator.
    """
    key = (process_type, solver_name)
    if key in _EXTRACTOR_REGISTRY and not replace:
        raise ValueError(f"Extractor already registered for {process_type}/{solver_name}.")
    _EXTRACTOR_REGISTRY[key] = extractor_cls
    return extractor_cls


def get(process_type: str, solver_name: str) -> type:
    """Return the adapter **class** registered for the given pair.

    Explicit registrations (via :func:`register` or plugins) are served
    from the cache. Unknown pairs fall back to lazy-loading the in-tree
    ``_BUILTIN_PATHS`` entry, if any.
    """
    key = (process_type, solver_name)
    cls = _REGISTRY.get(key)
    if cls is not None:
        return cls
    cls = _load_builtin(key)
    if cls is not None:
        return cls
    known = sorted(set(_REGISTRY) | set(_BUILTIN_PATHS))
    raise KeyError(
        f"No solver adapter registered for {process_type}/{solver_name}. Known pairs: {known}."
    )


def capabilities(process_type: str, solver_name: str) -> Capabilities:
    """Return the declared runtime capabilities for one adapter pair."""
    key = (process_type, solver_name)
    if key not in _REGISTRY:
        builtin = _BUILTIN_CAPABILITIES.get(key)
        if builtin is not None:
            return builtin
    cls = get(process_type, solver_name)
    declared = getattr(cls, "capabilities", None)
    if declared is not None:
        return frozenset(str(item) for item in declared)
    builtin = _BUILTIN_CAPABILITIES.get(key)
    if builtin is not None:
        return builtin
    return frozenset({process_type})


def get_solver_adapter(process_type: str, solver_name: str) -> Any:
    """Return a freshly-instantiated adapter for ``(process_type, solver_name)``.

    Convenience wrapper used by the simulation runner. The returned object is
    a new instance of the registered class; callers that need a class only
    should use :func:`get` instead.
    """
    cls = get(process_type, solver_name)
    return cls()


def get_extractor(process_type: str, solver_name: str) -> type:
    """Return the extractor class for ``(process_type, solver_name)``.

    Raises ``KeyError`` when no extractor is registered or declared as a
    built-in.
    """
    key = (process_type, solver_name)
    cls = _EXTRACTOR_REGISTRY.get(key)
    if cls is not None:
        return cls
    cls = _load_builtin_extractor(key)
    if cls is not None:
        return cls
    if not _EXTRACTOR_PLUGINS_LOADED:
        load_extractor_plugins()
        cls = _EXTRACTOR_REGISTRY.get(key)
        if cls is not None:
            return cls
    known = sorted(set(_EXTRACTOR_REGISTRY) | set(_BUILTIN_EXTRACTOR_PATHS))
    raise KeyError(f"No extractor registered for {process_type}/{solver_name}. Known: {known}.")


def get_extractor_instance(process_type: str, solver_name: str) -> Any | None:
    """Return a freshly-instantiated extractor, or ``None`` when unknown.

    ``post_run_results`` treats ``None`` as a configuration error.
    """
    try:
        cls = get_extractor(process_type, solver_name)
    except KeyError:
        return None
    return cls()


def unregister(process_type: str, solver_name: str) -> None:
    """Remove an adapter entry (primarily for tests).

    Also drops any matching entry from ``_BUILTIN_PATHS`` so a subsequent
    ``get`` call does not silently lazy-reload the built-in. Callers that
    remove a built-in are expected to re-register or restore the path
    themselves (fixtures typically snapshot/restore both dicts).
    """
    key = (process_type, solver_name)
    _REGISTRY.pop(key, None)
    _BUILTIN_PATHS.pop(key, None)
    _BUILTIN_CAPABILITIES.pop(key, None)


def unregister_extractor(process_type: str, solver_name: str) -> None:
    """Remove an extractor entry (primarily for tests).

    Also drops any matching entry from ``_BUILTIN_EXTRACTOR_PATHS`` so a
    subsequent ``get_extractor`` call does not lazy-reload the built-in.
    """
    key = (process_type, solver_name)
    _EXTRACTOR_REGISTRY.pop(key, None)
    _BUILTIN_EXTRACTOR_PATHS.pop(key, None)


def list_pairs() -> list[AdapterKey]:
    """Return all known pairs, sorted for stable output.

    Includes both pairs explicitly registered (in-process or via plugins)
    and in-tree built-ins declared in ``_BUILTIN_PATHS`` — even when the
    latter have not been lazy-loaded yet.
    """
    return sorted(set(_REGISTRY) | set(_BUILTIN_PATHS))


def list_extractor_pairs() -> list[AdapterKey]:
    """Return all ``(process_type, solver_name)`` pairs with a registered extractor."""
    return sorted(set(_EXTRACTOR_REGISTRY) | set(_BUILTIN_EXTRACTOR_PATHS))


def pairs_for_process(process_type: str) -> Iterable[AdapterKey]:
    """Yield all known pairs whose process type matches."""
    return (k for k in list_pairs() if k[0] == process_type)


def is_adapter(obj: object) -> bool:
    """Return ``True`` when *obj* structurally conforms to ``SolverAdapter``."""
    return isinstance(obj, SolverAdapter)


def known_process_types() -> set[str]:
    """Return the set of process types declared by any registered adapter."""
    return {key[0] for key in list_pairs()}


def required_bindings(process_type: str, solver_name: str) -> tuple[AdapterKey, ...]:
    """Return the earlier capability requirements declared by one adapter.

    The ``requires`` class attribute on the adapter is the source of truth.
    It returns a tuple of ``(process_type, solver_name)`` capabilities that
    must already be satisfied by earlier runs in the plan.

    Raises
    ------
    ValueError
        When the pair is not registered — the planner expects a precise
        error, not a silent empty tuple.
    """
    try:
        cls = get(process_type, solver_name)
    except KeyError as exc:
        raise ValueError(
            f"Unsupported simulation process/solver pair: {process_type}/{solver_name}."
        ) from exc
    return tuple(getattr(cls, "requires", ()))


def is_supported(process_type: str, solver_name: str) -> bool:
    """Return ``True`` when the pair is declared in the adapter registry."""
    return (process_type, solver_name) in set(list_pairs())


def load_plugins(*, force: bool = False) -> int:
    """Discover and register adapters declared via the ``hydromodpy.solver``
    entry-points group.

    Each entry-point name must be ``"<process_type>_<solver_name>"`` (e.g.
    ``"flow_modflow6"``). The loaded value must be a ``SolverAdapter`` class.
    Already-registered pairs are kept (an entry-point cannot replace an
    in-process registration unless ``force=True``).

    Returns the number of newly registered adapters.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        eps = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]

    for ep in eps:
        name = ep.name
        if "_" not in name:
            logger.warning(
                "solver plugin %r ignored: entry-point name must be "
                "'<process_type>_<solver_name>' (got %r)",
                ep,
                name,
            )
            continue
        process_type, _, solver_name = name.partition("_")
        if (process_type, solver_name) in _REGISTRY and not force:
            continue
        try:
            adapter_cls = ep.load()
        except Exception as exc:  # pragma: no cover - exercised via tests with stubs
            logger.warning(
                "failed to load solver plugin %r: %s",
                ep,
                exc,
            )
            continue
        register(process_type, solver_name, adapter_cls, replace=force)
        count += 1
    _PLUGINS_LOADED = True
    return count


def load_extractor_plugins(*, force: bool = False) -> int:
    """Discover and register extractors declared via the
    ``hydromodpy.solver.extractor`` entry-points group.

    Each entry-point name must be ``"<process_type>_<solver_name>"`` (e.g.
    ``"flow_modflow6"``). The loaded value must be a class implementing the
    extractor contract (``extract`` / ``derive``).
    """
    global _EXTRACTOR_PLUGINS_LOADED
    if _EXTRACTOR_PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        eps = entry_points(group=EXTRACTOR_ENTRY_POINT_GROUP)
    except TypeError:
        eps = entry_points().get(EXTRACTOR_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]

    for ep in eps:
        name = str(ep.name).strip()
        if "_" not in name:
            logger.warning(
                "extractor plugin %r ignored: entry-point name must be "
                "'<process_type>_<solver_name>' (got %r)",
                ep,
                name,
            )
            continue
        process_type, _, solver_name = name.partition("_")
        if (process_type, solver_name) in _EXTRACTOR_REGISTRY and not force:
            continue
        try:
            extractor_cls = ep.load()
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "failed to load extractor plugin %r: %s",
                ep,
                exc,
            )
            continue
        register_extractor(process_type, solver_name, extractor_cls, replace=force)
        count += 1
    _EXTRACTOR_PLUGINS_LOADED = True
    return count


__all__ = [
    "Capabilities",
    "EXTRACTOR_ENTRY_POINT_GROUP",
    "ENTRY_POINT_GROUP",
    "AdapterKey",
    "capabilities",
    "get",
    "get_extractor",
    "get_extractor_instance",
    "get_solver_adapter",
    "is_adapter",
    "is_supported",
    "known_process_types",
    "list_extractor_pairs",
    "list_pairs",
    "load_extractor_plugins",
    "load_plugins",
    "pairs_for_process",
    "register",
    "register_extractor",
    "required_bindings",
    "unregister",
    "unregister_extractor",
]
