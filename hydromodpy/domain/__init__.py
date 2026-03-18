"""Domain module for HydroModPy."""

from hydromodpy.domain.domain import Domain
from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.domain.depth_model import (
    ConstantThicknessDepthModel,
    DepthModelConfig,
    FlatSubstratumDepthModel,
)
from hydromodpy.domain.spatial_support import (
    GeneratedBandsSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
)
from hydromodpy.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    DomainSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
    GeologySupportConfig,
)

__all__ = [
    "Domain",
    "DomainConfig",
    "DepthModelConfig",
    "ConstantThicknessDepthModel",
    "FlatSubstratumDepthModel",
    "DomainSupportConfig",
    "GeneratedBandsSupportConfig",
    "GeneratedRingsSupportConfig",
    "CatchmentZonesSupportConfig",
    "GeologySupportConfig",
    "RasterZonesSupportField",
    "GeneratedBandsSupportField",
    "GeneratedRingsSupportField",
    "SupportBuildContext",
    "build_default_spatial_support_provider_registry",
]
