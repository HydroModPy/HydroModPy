"""Whitebox Workflows backend split by concern.

The public entry point is :class:`WhiteboxWorkflowsBackend`, a thin facade
that composes thematic sub-backends:

- :class:`WhiteboxRasterBackend` for raster/vector IO and shared environment.
- :class:`WhiteboxFlowBackend` for flow accumulation and stream products.
- :class:`WhiteboxDelineationBackend` for pour points and watersheds.
"""

from __future__ import annotations

from hydromodpy.catchment.delineation.registry import clear_backend_cache, get_backend
from hydromodpy.catchment.delineation.whitebox_workflows_backend.delineation import (
    WhiteboxDelineationBackend,
)
from hydromodpy.catchment.delineation.whitebox_workflows_backend.flow import WhiteboxFlowBackend
from hydromodpy.catchment.delineation.whitebox_workflows_backend.raster import WhiteboxRasterBackend

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


def clear_whitebox_backend_cache() -> None:
    """Clear the shared workflows backend singleton, the one the registry caches."""
    clear_backend_cache()


def get_whitebox_backend(kind: str | None = None) -> WhiteboxWorkflowsBackend:
    """Return the shared workflows backend used by runtime code.

    It is the instance :func:`hydromodpy.catchment.delineation.registry.get_backend`
    returns, so one process holds one Whitebox environment. The ``kind`` check
    stays here: the registry also accepts ``"whitebox"``, this function does not.
    """
    return get_backend(_normalize_whitebox_backend_kind(kind))
