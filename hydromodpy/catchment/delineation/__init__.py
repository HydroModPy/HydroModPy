"""The Whitebox environment of the process, and the two helpers that read a backend.

One process holds one Whitebox environment. ``get_whitebox_backend`` builds it on the first
call and returns the same object after. Importing this package does not load
``whitebox_workflows``, so the classes of the backend are imported from
``hydromodpy.catchment.delineation.whitebox_workflows_backend``.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.catchment.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend


@cache
def get_whitebox_backend() -> WhiteboxWorkflowsBackend:
    """Return the one Whitebox facade of the process, built on the first call."""
    try:
        from hydromodpy.catchment.delineation.whitebox_workflows_backend import (
            WhiteboxWorkflowsBackend,
        )
    except ImportError as exc:
        raise ImportError(
            f"Backend 'whitebox_workflows' is not available: missing optional dependency ({exc})."
        ) from exc
    return WhiteboxWorkflowsBackend()


def clear_whitebox_backend_cache() -> None:
    """Drop the shared facade, so the next call builds a new one (used by tests)."""
    get_whitebox_backend.cache_clear()


def resolve_delineation_backend(backend: object | None = None) -> object:
    """Return the injected backend, or the Whitebox facade of the process."""
    if backend is not None:
        return backend
    return get_whitebox_backend()


def backend_has_callables(backend: object, component_name: str, *method_names: str) -> bool:
    """Return true when one backend component exposes all named methods."""
    component = getattr(backend, component_name, None)
    if component is None:
        return False
    return all(callable(getattr(component, method_name, None)) for method_name in method_names)
