"""
Flow Process Package
====================

Public exports for the flow process layer:
- runtime process object (`Flow`),
- typed configuration model (`FlowConfig`),
- typed payload models (IC, BC, sinks/sources).
"""

from .flow import Flow
from .boundary_conditions import FlowBoundaryConditionConfig
from .flow_config import FlowConfig
from .initial_conditions import FlowInitialCondition, FlowInitialConditions
from .sinks_sources import FlowSinksSourcesConfig, FlowWellConfig

__all__ = [
    "Flow",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "FlowBoundaryConditionConfig",
    "FlowWellConfig",
    "FlowSinksSourcesConfig",
    "FlowConfig",
]

