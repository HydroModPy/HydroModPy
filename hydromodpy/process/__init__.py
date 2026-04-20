"""Public process namespace.

Canonical process objects live in concrete subpackages such as
``hydromodpy.process.flow`` and ``hydromodpy.process.transport``.
"""

from __future__ import annotations

from hydromodpy.process.base import (
    BoundaryCondition,
    InitialCondition,
    Process,
    ProcessSpatial,
    ProcessSpatialConfig,
    SinkSource,
)
from hydromodpy.process.flow import (
    Flow,
    FlowConfig,
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.process.transport import (
    Transport,
    TransportConfig,
    TransportInitialConditions,
)

__all__ = [
    "BoundaryCondition",
    "Flow",
    "FlowConfig",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "InitialCondition",
    "Process",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
    "Transport",
    "TransportConfig",
    "TransportInitialConditions",
]
