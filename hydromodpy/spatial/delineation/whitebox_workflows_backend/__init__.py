"""Whitebox Workflows backend split by concern.

The public entry point is :class:`WhiteboxWorkflowsBackend`, a thin facade
that composes thematic sub-backends:

- :class:`WhiteboxRasterBackend` for raster/vector IO and shared environment.
- :class:`WhiteboxFlowBackend` for flow accumulation and stream products.
- :class:`WhiteboxDelineationBackend` for pour points and watersheds.
"""

from __future__ import annotations

from functools import lru_cache

from hydromodpy.spatial.delineation.whitebox_workflows_backend.delineation import (
    WhiteboxDelineationBackend,
)
from hydromodpy.spatial.delineation.whitebox_workflows_backend.flow import (
    WhiteboxFlowBackend,
)
from hydromodpy.spatial.delineation.whitebox_workflows_backend.raster import (
    WhiteboxRasterBackend,
)

__all__ = [
    "WhiteboxDelineationBackend",
    "WhiteboxFlowBackend",
    "WhiteboxRasterBackend",
    "WhiteboxWorkflowsBackend",
    "clear_whitebox_backend_cache",
    "get_whitebox_backend",
]


class WhiteboxWorkflowsBackend:
    """Facade aggregating raster IO, flow analysis and delineation backends."""

    def __init__(self) -> None:
        self.raster = WhiteboxRasterBackend()
        self.flow = WhiteboxFlowBackend(self.raster)
        self.delineation = WhiteboxDelineationBackend(self.raster)


def _normalize_whitebox_backend_kind(kind: str | None = None) -> str:
    """Normalize backend selector while keeping HydroModPy workflows-only."""
    value = "whitebox_workflows" if kind is None else str(kind)
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "whitebox_workflows",
        "whiteboxworkflow",
        "workflows",
        "wbw",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unsupported whitebox backend {value!r}. "
            "HydroModPy now supports only 'whitebox_workflows'."
        )
    return "whitebox_workflows"


@lru_cache(maxsize=1)
def _get_cached_whitebox_backend(kind: str = "whitebox_workflows") -> WhiteboxWorkflowsBackend:
    _normalize_whitebox_backend_kind(kind)
    return WhiteboxWorkflowsBackend()


def clear_whitebox_backend_cache() -> None:
    """Clear the shared workflows backend singleton."""
    _get_cached_whitebox_backend.cache_clear()


def get_whitebox_backend(kind: str | None = None) -> WhiteboxWorkflowsBackend:
    """Return the shared workflows backend used by runtime code."""
    return _get_cached_whitebox_backend(_normalize_whitebox_backend_kind(kind))
