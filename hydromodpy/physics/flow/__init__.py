"""
Flow Process Package
====================

Public exports for the flow process layer:
- runtime process object (`Flow`),
- typed configuration model (`FlowConfig`),
- typed payload models (IC, BC, sinks/sources).
"""

from .boundary_conditions import CauchyBC, DirichletBC, FlowBoundaryConditionConfig, RobinBC
from .flow import Flow
from .flow_config import FlowConfig, FlowParam
from .initial_conditions import FlowInitialCondition, FlowInitialConditions
from .physical_properties import FlowPhysicalProperties
from .regime import FlowRegime, normalize_flow_regime
from .sinks_sources import FlowSinksSourcesConfig, FlowWellConfig

__all__ = [
    "Flow",
    "FlowRegime",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "DirichletBC",
    "CauchyBC",
    "RobinBC",
    "FlowBoundaryConditionConfig",
    "FlowWellConfig",
    "FlowSinksSourcesConfig",
    "FlowParam",
    "FlowConfig",
    "FlowPhysicalProperties",
    "normalize_flow_regime",
]
