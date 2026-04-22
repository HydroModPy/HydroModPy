"""Public process namespace.

Canonical process objects live in concrete subpackages such as
``hydromodpy.physics.flow`` and ``hydromodpy.physics.transport``.
"""

from __future__ import annotations

from hydromodpy.physics.base import (
    BoundaryCondition,
    InitialCondition,
    Process,
    ProcessSpatial,
    ProcessSpatialConfig,
    SinkSource,
)
from hydromodpy.physics.flow import (
    Flow,
    FlowConfig,
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.physics.transport import (
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
