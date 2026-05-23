"""DEM variable - digital elevation model acquisition, caching, and serving."""

from hydromodpy.data.variables.dem import apis
from hydromodpy.data.variables.dem.config import DemConfig
from hydromodpy.data.variables.dem.manager import DemManager

__all__ = ("DemConfig", "DemManager", "apis")
