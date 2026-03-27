"""Spatial layer for HydroModPy.

This package groups the spatial core of the library:

- low-level raster/surface primitives;
- geographic preprocessing;
- domain assembly;
- field parameter supports;
- unified mesh exchange objects.
"""

from hydromodpy.spatial.catchment_zones_field import CatchmentZonesField
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.field import FieldParam
from hydromodpy.spatial.geographic import Geographic, GeographicConfig
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

__all__ = [
    "CatchmentZonesField",
    "RasterSupport",
    "Surface",
    "PreparedSurfaceSampler",
    "Domain",
    "DomainConfig",
    "FieldParam",
    "Geographic",
    "GeographicConfig",
    "CellBlock",
    "CellType",
    "HydroMesh",
]
