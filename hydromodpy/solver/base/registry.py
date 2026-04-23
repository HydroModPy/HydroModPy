"""Single ``(process_type, solver_name) → adapter class`` registry.

This module is the canonical merge of the historical registries that used to
live in ``solver/compatibility`` (class-based) and ``simulation/adapters``
(instance-based). It now serves both consumers:

- Adapter authors register their **class** here (or via the
  ``hydromodpy.solver`` entry-points group, see :func:`load_plugins`).
- The simulation runner asks for an **instance** through
  :func:`get_solver_adapter`, which instantiates the registered class on
  demand. This matches the lifecycle intent of ``SolverRunner`` (one adapter
  = one run) while preserving the lightweight semantics of a static catalog.

Built-in adapters shipped in-tree are declared as dotted paths in
``_BUILTIN_PATHS`` and imported lazily on first lookup. That keeps
``hydromodpy.simulation`` free of eager imports of ``hydromodpy.solver``
concrete backends at package-load time.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import Any

from hydromodpy.solver.base.protocol import SolverRunner

logger = logging.getLogger(__name__)

AdapterKey = tuple[str, str]
ENTRY_POINT_GROUP = "hydromodpy.solver"

_REGISTRY: dict[AdapterKey, type] = {}
_PLUGINS_LOADED = False

# Dotted paths to in-tree adapter classes. Loaded lazily by :func:`get` on
# first lookup so that importing this module (and therefore the whole
# ``hydromodpy.simulation`` stack) does not pull every solver backend.
# Format: ``"<module>:<class>"``.
_BUILTIN_PATHS: dict[AdapterKey, str] = {
    ("flow", "modflownwt"): "hydromodpy.solver.modflow_nwt.adapters.flow:ModflowNwtFlowAdapter",
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
        "modflow6gwt",
    ): "hydromodpy.solver.modflow6.adapters.transport:Modflow6GwtTransportAdapter",
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


def get_solver_adapter(process_type: str, solver_name: str) -> Any:
    """Return a freshly-instantiated adapter for ``(process_type, solver_name)``.

    Convenience wrapper used by the simulation runner. The returned object is
    a new instance of the registered class; callers that need a class only
    should use :func:`get` instead.
    """
    cls = get(process_type, solver_name)
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


def list_pairs() -> list[AdapterKey]:
    """Return all known pairs, sorted for stable output.

    Includes both pairs explicitly registered (in-process or via plugins)
    and in-tree built-ins declared in ``_BUILTIN_PATHS`` — even when the
    latter have not been lazy-loaded yet.
    """
    return sorted(set(_REGISTRY) | set(_BUILTIN_PATHS))


def pairs_for_process(process_type: str) -> Iterable[AdapterKey]:
    """Yield all known pairs whose process type matches."""
    return (k for k in list_pairs() if k[0] == process_type)


def is_adapter(obj: object) -> bool:
    """Return ``True`` when *obj* structurally conforms to ``SolverRunner``."""
    return isinstance(obj, SolverRunner)


def load_plugins(*, force: bool = False) -> int:
    """Discover and register adapters declared via the ``hydromodpy.solver``
    entry-points group.

    Each entry-point name must be ``"<process_type>_<solver_name>"`` (e.g.
    ``"flow_modflow6"``). The loaded value must be a ``SolverRunner`` class.
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
        # Older importlib.metadata API: select group ourselves.
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


__all__ = [
    "AdapterKey",
    "ENTRY_POINT_GROUP",
    "get",
    "get_solver_adapter",
    "is_adapter",
    "list_pairs",
    "load_plugins",
    "pairs_for_process",
    "register",
    "unregister",
]
