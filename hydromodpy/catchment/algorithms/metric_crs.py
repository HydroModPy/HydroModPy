"""Areas of polygon layers, measured in one projected CRS.

A layer in a geographic CRS is projected first, so an area is in square meters
whatever CRS the file was written in. Lengths and the projection itself live in
:mod:`hydromodpy.core.io.crs`, which the display layer shares.
"""

from __future__ import annotations

from hydromodpy.catchment.algorithms.catchment_domain import catchment_area_m2
from hydromodpy.core.io.crs import project_gdf_for_metric_operations

__all__ = ["measure_polygon_area_m2"]


def measure_polygon_area_m2(
    gdf,
    *,
    fallback_crs: str | object | None = None,
) -> float:
    """Return total polygon area in m² after coercing to one metric CRS."""
    if gdf is None or gdf.empty:
        return 0.0
    return catchment_area_m2(project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs))
