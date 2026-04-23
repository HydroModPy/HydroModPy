"""Shared process contracts used by HydroModPy internals.

This module provides the explicit import path for generic process-layer
building blocks such as ``ProcessSpatial`` and ``ProcessSpatialConfig``.
Concrete business objects should continue to live under
``hydromodpy.physics.flow`` and ``hydromodpy.physics.transport``.
"""

from hydromodpy.physics.base import (
    BoundaryCondition,
    InitialCondition,
    ProcessSpatial,
    ProcessSpatialConfig,
    SinkSource,
)

__all__ = [
    "BoundaryCondition",
    "InitialCondition",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
]
