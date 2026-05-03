"""
Flow Process Package
====================

Public exports for the flow process layer:
- runtime process object (`Flow`),
- typed configuration model (`FlowConfig`),
- typed payload models (IC, BC, sinks/sources).
"""

from .boundary_conditions import FlowBoundaryConditionConfig
from .flow import Flow
from .flow_config import FlowConfig
from .initial_conditions import FlowInitialCondition, FlowInitialConditions
from .physical_properties import FlowPhysicalProperties
from .regime import FlowRegime, FlowRegimeInput, is_permanent_flow_regime, normalize_flow_regime
from .sinks_sources import FlowSinksSourcesConfig, FlowWellConfig

__all__ = [
    "Flow",
    "FlowRegime",
    "FlowRegimeInput",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "FlowBoundaryConditionConfig",
    "FlowWellConfig",
    "FlowSinksSourcesConfig",
    "FlowConfig",
    "FlowPhysicalProperties",
    "is_permanent_flow_regime",
    "normalize_flow_regime",
]
