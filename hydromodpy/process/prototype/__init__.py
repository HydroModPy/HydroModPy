"""
Prototype Package: Shared Process Building Blocks
=================================================

This package exposes generic, process-agnostic components used by concrete
process modules (for example `flow`, `transport`):

- base runtime abstraction (`ProcessSpatial`),
- base configuration schema (`ProcessSpatialConfig`),
- shared payload models (`InitialCondition`, `BoundaryCondition`, `SinkSource`),
- shared normalization helpers.

Import from this package when you need reusable primitives that should remain
independent from process-specific business rules.
"""

from .boundary_conditions import BoundaryCondition
from .boundary_conditions_config import normalize_boundary_condition_payload
from .initial_conditions import InitialCondition
from .initial_conditions_config import normalize_initial_condition_payload
from .process_spatial import Process, ProcessSpatial, TInitialConditions
from .process_spatial_config import ProcessSpatialConfig
from .sinks_sources import SinkSource
from .sinks_sources_config import normalize_sink_source_payload

__all__ = [
    "InitialCondition",
    "BoundaryCondition",
    "SinkSource",
    "normalize_initial_condition_payload",
    "normalize_boundary_condition_payload",
    "normalize_sink_source_payload",
    "ProcessSpatialConfig",
    "TInitialConditions",
    "ProcessSpatial",
    "Process",
]
