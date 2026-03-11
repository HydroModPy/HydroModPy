"""Domain module for HydroModPy."""

from hydromodpy.domain.catchment_zones_field import CatchmentZonesField
from hydromodpy.domain.domain import Domain
from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.domain.depth_model import (
    ConstantThicknessDepthModel,
    DepthModelConfig,
    FlatSubstratumDepthModel,
)
from hydromodpy.domain.raster_support import RasterSupport
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
from hydromodpy.domain.surface import Surface

__all__ = [
    "Domain",
    "DomainConfig",
    "CatchmentZonesField",
    "DepthModelConfig",
    "ConstantThicknessDepthModel",
    "FlatSubstratumDepthModel",
    "RasterSupport",
    "Surface",
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
