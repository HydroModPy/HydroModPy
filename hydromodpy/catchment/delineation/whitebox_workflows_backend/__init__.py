"""Whitebox Workflows backend split by concern.

The public entry point is :class:`WhiteboxWorkflowsBackend`, a thin facade
that composes thematic sub-backends:

- :class:`WhiteboxRasterBackend` for raster/vector IO and shared environment.
- :class:`WhiteboxFlowBackend` for flow accumulation and stream products.
- :class:`WhiteboxDelineationBackend` for pour points and watersheds.
"""

from __future__ import annotations

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
]


class WhiteboxWorkflowsBackend:
    """Facade aggregating raster IO, flow analysis and delineation backends."""

    def __init__(self) -> None:
        self.raster = WhiteboxRasterBackend()
        self.flow = WhiteboxFlowBackend(self.raster)
        self.delineation = WhiteboxDelineationBackend(self.raster)
