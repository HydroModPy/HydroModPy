"""
Flow Process Package
====================

Public exports for the flow process layer:
- runtime process object (`Flow`),
- typed configuration model (`FlowConfig`),
- typed payload models (IC, BC, sinks/sources).
"""

from .boundary_condition_registry import (
    FLOW_BOUNDARY_DEFINITIONS,
    SUPPORTED_FLOW_BOUNDARY_IDS,
    BoundaryConditionBundle,
    FlowBoundaryDefinition,
    boundary_definition,
    supported_boundary_ids_for_backend,
)
from .boundary_conditions import FlowBoundaryConditionConfig
from .flow import Flow
from .flow_config import FlowConfig
from .initial_conditions import FlowInitialCondition, FlowInitialConditions
from .physical_properties import FlowPhysicalProperties
from .regime import FlowRegime, normalize_flow_regime
from .sinks_sources import FlowSinksSourcesConfig, FlowWellConfig

__all__ = [
    "Flow",
    "FlowRegime",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "FlowBoundaryConditionConfig",
    "BoundaryConditionBundle",
    "FlowBoundaryDefinition",
    "FLOW_BOUNDARY_DEFINITIONS",
    "SUPPORTED_FLOW_BOUNDARY_IDS",
    "boundary_definition",
    "supported_boundary_ids_for_backend",
    "FlowWellConfig",
    "FlowSinksSourcesConfig",
    "FlowConfig",
    "FlowPhysicalProperties",
    "normalize_flow_regime",
]
