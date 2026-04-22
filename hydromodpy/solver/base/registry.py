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
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any, Iterable

from hydromodpy.solver.base.protocol import SolverRunner

logger = logging.getLogger(__name__)

AdapterKey = tuple[str, str]
ENTRY_POINT_GROUP = "hydromodpy.solver"

_REGISTRY: dict[AdapterKey, type] = {}
_PLUGINS_LOADED = False


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
        raise ValueError(
            f"Solver adapter already registered for {process_type}/{solver_name}."
        )
    _REGISTRY[key] = adapter_cls
    return adapter_cls


def get(process_type: str, solver_name: str) -> type:
    """Return the adapter **class** registered for the given pair."""
    key = (process_type, solver_name)
    if key not in _REGISTRY:
        raise KeyError(
            f"No solver adapter registered for {process_type}/{solver_name}. "
            f"Known pairs: {sorted(_REGISTRY)}."
        )
    return _REGISTRY[key]


def get_solver_adapter(process_type: str, solver_name: str) -> Any:
    """Return a freshly-instantiated adapter for ``(process_type, solver_name)``.

    Convenience wrapper used by the simulation runner. The returned object is
    a new instance of the registered class; callers that need a class only
    should use :func:`get` instead.
    """
    cls = get(process_type, solver_name)
    return cls()


def unregister(process_type: str, solver_name: str) -> None:
    """Remove an adapter entry (primarily for tests)."""
    _REGISTRY.pop((process_type, solver_name), None)


def list_pairs() -> list[AdapterKey]:
    """Return the list of registered pairs, sorted for stable output."""
    return sorted(_REGISTRY)


def pairs_for_process(process_type: str) -> Iterable[AdapterKey]:
    """Yield all registered pairs whose process type matches."""
    return (k for k in sorted(_REGISTRY) if k[0] == process_type)


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
                ep, name,
            )
            continue
        process_type, _, solver_name = name.partition("_")
        if (process_type, solver_name) in _REGISTRY and not force:
            continue
        try:
            adapter_cls = ep.load()
        except Exception as exc:  # pragma: no cover - exercised via tests with stubs
            logger.warning(
                "failed to load solver plugin %r: %s", ep, exc,
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
