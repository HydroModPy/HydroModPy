"""Catchment delineation backends.

Runtime entry points:

- ``DelineationBackend`` - high-level Protocol (see :mod:`.base`).
- ``WhiteboxWorkflowsBackend`` - facade aggregating raster IO, flow analysis,
  and delineation sub-backends.
- ``WhiteboxRasterBackend`` / ``WhiteboxFlowBackend`` /
  ``WhiteboxDelineationBackend`` - thematic sub-backends accessible via the
  facade attributes ``raster`` / ``flow`` / ``delineation``.
- ``get_backend(name)`` - resolve a registered backend by name with
  graceful fallback when an optional dependency is missing.
- ``get_whitebox_backend()`` - shortcut returning the default
  workflows-backed facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.spatial.delineation.base import DelineationBackend
from hydromodpy.spatial.delineation.registry import (
    available_backends,
    get_backend,
    register_backend,
)

if TYPE_CHECKING:
    from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
        WhiteboxWorkflowsBackend,
    )

__all__ = [
    "DelineationBackend",
    "WhiteboxDelineationBackend",
    "WhiteboxFlowBackend",
    "WhiteboxRasterBackend",
    "WhiteboxWorkflowsBackend",
    "available_backends",
    "clear_whitebox_backend_cache",
    "get_backend",
    "get_whitebox_backend",
    "register_backend",
]


def clear_whitebox_backend_cache() -> None:
    """Clear the shared workflows backend singleton."""
    from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
        clear_whitebox_backend_cache as _clear_whitebox_backend_cache,
    )

    _clear_whitebox_backend_cache()


def get_whitebox_backend(kind: str | None = None) -> WhiteboxWorkflowsBackend:
    """Return the shared workflows backend used by runtime code."""
    from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
        get_whitebox_backend as _get_whitebox_backend,
    )

    return _get_whitebox_backend(kind)


def __getattr__(name: str):
    if name in {
        "WhiteboxDelineationBackend",
        "WhiteboxFlowBackend",
        "WhiteboxRasterBackend",
        "WhiteboxWorkflowsBackend",
    }:
        from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
            WhiteboxDelineationBackend,
            WhiteboxFlowBackend,
            WhiteboxRasterBackend,
            WhiteboxWorkflowsBackend,
        )

        mapping = {
            "WhiteboxDelineationBackend": WhiteboxDelineationBackend,
            "WhiteboxFlowBackend": WhiteboxFlowBackend,
            "WhiteboxRasterBackend": WhiteboxRasterBackend,
            "WhiteboxWorkflowsBackend": WhiteboxWorkflowsBackend,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
