"""Catchment delineation backends.

Runtime entry points:

- ``DelineationBackend`` - high-level Protocol (see :mod:`.base`).
- ``WhiteboxBackend`` - low-level file-based Protocol (legacy contract).
- ``get_backend(name)`` - resolve a registered backend by name with
  graceful fallback when an optional dependency is missing.
- ``get_whitebox_backend()`` - shortcut returning the default
  workflows-backed instance, kept as the direct replacement for the
  old ``hydromodpy.core.backends.get_whitebox_backend`` API.
"""

from __future__ import annotations

from hydromodpy.spatial.delineation.base import DelineationBackend, WhiteboxBackend
from hydromodpy.spatial.delineation.registry import (
    available_backends,
    get_backend,
    register_backend,
)

__all__ = [
    "DelineationBackend",
    "WhiteboxBackend",
    "WhiteboxWorkflowsBackend",
    "available_backends",
    "clear_whitebox_backend_cache",
    "get_backend",
    "get_whitebox_backend",
    "register_backend",
]


def __getattr__(name: str):
    if name in {
        "WhiteboxWorkflowsBackend",
        "clear_whitebox_backend_cache",
        "get_whitebox_backend",
    }:
        from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
            WhiteboxWorkflowsBackend,
            clear_whitebox_backend_cache,
            get_whitebox_backend,
        )

        mapping = {
            "WhiteboxWorkflowsBackend": WhiteboxWorkflowsBackend,
            "clear_whitebox_backend_cache": clear_whitebox_backend_cache,
            "get_whitebox_backend": get_whitebox_backend,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
