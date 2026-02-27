"""Domain module for HydroModPy."""

from hydromodpy.domain.domain import Domain
from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.domain.depth_model import (
    ConstantThicknessDepthModel,
    DepthModelConfig,
    FlatSubstratumDepthModel,
)
from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface

__all__ = [
    "Domain",
    "DomainConfig",
    "DepthModelConfig",
    "ConstantThicknessDepthModel",
    "FlatSubstratumDepthModel",
    "RasterSupport",
    "Surface",
]
