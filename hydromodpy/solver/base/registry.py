"""Small ``(process_type, solver_name) → adapter class`` registry.

This is the single source of truth for looking up solver adapter classes.
It replaces scattered dict registries that used to live inside
``simulation/adapters`` and ``solver/compatibility``.

The registry stores *classes*, not instances, so consumers instantiate
adapters freshly per run. This matches the lifecycle intent of
``SolverRunner`` (one adapter = one run).
"""

from __future__ import annotations

from typing import Iterable

from hydromodpy.solver.base.protocol import SolverRunner

AdapterKey = tuple[str, str]

_REGISTRY: dict[AdapterKey, type] = {}


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
    """Return the adapter class registered for the given pair."""
    key = (process_type, solver_name)
    if key not in _REGISTRY:
        raise KeyError(
            f"No solver adapter registered for {process_type}/{solver_name}. "
            f"Known pairs: {sorted(_REGISTRY)}."
        )
    return _REGISTRY[key]


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


__all__ = [
    "AdapterKey",
    "get",
    "is_adapter",
    "list_pairs",
    "pairs_for_process",
    "register",
    "unregister",
]
