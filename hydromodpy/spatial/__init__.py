"""Shared spatial primitives used across HydroModPy.

This module provides the foundational spatial data structures that multiple
packages depend on (geographic, domain, solver, ...).  Keeping them in a
dedicated low-level package avoids circular dependencies between higher-level
modules.

Exported types
--------------
- ``RasterSupport`` -- georeferencing metadata for one 2D raster.
- ``Surface``       -- one 2D raster array together with its spatial support.
- ``CatchmentZonesField`` -- classified raster of catchment zone codes.
"""

from hydromodpy.spatial.catchment_zones_field import CatchmentZonesField
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface

__all__ = [
    "CatchmentZonesField",
    "RasterSupport",
    "Surface",
]
