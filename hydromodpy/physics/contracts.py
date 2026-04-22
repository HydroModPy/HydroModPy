"""Shared process contracts used by HydroModPy internals.

This module provides the explicit import path for generic process-layer
building blocks such as ``ProcessSpatial`` and ``ProcessSpatialConfig``.
Concrete business objects should continue to live under
``hydromodpy.physics.flow`` and ``hydromodpy.physics.transport``.

The root ``hydromodpy.physics`` package still re-exports these symbols for
backward compatibility, but internal code should import from this module or
from concrete subpackages instead of depending on the root facade.
"""

from hydromodpy.physics.base import (
    BoundaryCondition,
    InitialCondition,
    Process,
    ProcessSpatial,
    ProcessSpatialConfig,
    SinkSource,
)

__all__ = [
    "BoundaryCondition",
    "InitialCondition",
    "Process",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
]
