"""Geographic figure helpers.

Provides :class:`GeoFigureMixin` for figures that draw on a map (CRS
awareness, scale bar, optional basemap) and a tiny ``basemaps`` helper
module.
"""

from __future__ import annotations

from hydromodpy.display.geo.mixin import GeoFigureMixin

__all__ = ["GeoFigureMixin"]
