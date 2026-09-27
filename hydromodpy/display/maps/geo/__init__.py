"""Geographic figure helpers.

Provides :class:`GeoFigureMixin` for figures that draw a vector map on
metric axes (a scale bar and a north arrow), and
:func:`project_gdf_for_metric_operations`, which puts a GeoDataFrame in a
metric CRS.
"""

from __future__ import annotations

from hydromodpy.display.maps.geo.mixin import GeoFigureMixin
from hydromodpy.display.maps.geo.projection import project_gdf_for_metric_operations

__all__ = ["GeoFigureMixin", "project_gdf_for_metric_operations"]
