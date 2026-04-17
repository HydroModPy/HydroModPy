"""Public process namespace.

Canonical process objects live in concrete subpackages such as
``hydromodpy.process.flow`` and ``hydromodpy.process.transport``.
Generic contracts remain re-exported here for backward compatibility, but
internal code should import them from ``hydromodpy.process.contracts``.
"""

from __future__ import annotations

import warnings

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

_LEGACY_CONTRACT_NAMES = {
    "BoundaryCondition",
    "InitialCondition",
    "Process",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
}

__all__ = [
    "Flow",
    "FlowConfig",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "Process",
    "InitialCondition",
    "BoundaryCondition",
    "SinkSource",
    "Transport",
    "TransportInitialConditions",
    "TransportConfig",
]


def __getattr__(name: str):
    if name in _LEGACY_CONTRACT_NAMES:
        from hydromodpy.process import contracts

        warnings.warn(
            f"'hydromodpy.process.{name}' is a backward-compatibility export. "
            f"Import it from 'hydromodpy.process.contracts' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(contracts, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
