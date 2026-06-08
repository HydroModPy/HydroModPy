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
from .boundary_conditions import CauchyBC, DirichletBC, FlowBoundaryConditionConfig, RobinBC
from .flow import Flow
from .flow_config import FlowConfig, FlowParam
from .initial_conditions import (
    FlowICBottom,
    FlowICCustom,
    FlowICSteadyState,
    FlowICTop,
    FlowICTopOffset,
    FlowInitialCondition,
    FlowInitialConditions,
)
from .physical_properties import FlowPhysicalProperties
from .regime import FlowRegime, normalize_flow_regime
from .sinks_sources import FlowLakeConfig, FlowSinksSourcesConfig, FlowWellConfig

__all__ = [
    "Flow",
    "FlowRegime",
    "FlowICBottom",
    "FlowICCustom",
    "FlowICSteadyState",
    "FlowICTop",
    "FlowICTopOffset",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "DirichletBC",
    "CauchyBC",
    "RobinBC",
    "FlowBoundaryConditionConfig",
    "BoundaryConditionBundle",
    "FlowBoundaryDefinition",
    "FLOW_BOUNDARY_DEFINITIONS",
    "SUPPORTED_FLOW_BOUNDARY_IDS",
    "boundary_definition",
    "supported_boundary_ids_for_backend",
    "FlowWellConfig",
    "FlowLakeConfig",
    "FlowSinksSourcesConfig",
    "FlowParam",
    "FlowConfig",
    "FlowPhysicalProperties",
    "normalize_flow_regime",
]
