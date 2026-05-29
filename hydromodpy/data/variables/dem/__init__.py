"""DEM variable - digital elevation model acquisition, caching, and serving."""

from hydromodpy.data.variables.dem import apis
from hydromodpy.data.variables.dem.config import (
    CustomDemSource,
    DemConfig,
    IgnGeoplateformeDemSource,
)
from hydromodpy.data.variables.dem.manager import DemManager

__all__ = (
    "CustomDemSource",
    "DemConfig",
    "DemManager",
    "IgnGeoplateformeDemSource",
    "apis",
)
