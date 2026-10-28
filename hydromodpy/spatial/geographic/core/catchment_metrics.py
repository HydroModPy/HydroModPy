"""Compute scalar metrics from catchment geometries.

Purpose
-------
Expose lightweight, deterministic geographic indicators used by orchestration
and diagnostics.

Current scope
-------------
Only catchment area (km2) is exposed here. An ``AREA`` attribute authored in
the shapefile wins over the geometry, every row summed.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from hydromodpy.spatial.geographic.core.catchment_domain import catchment_area_m2


def compute_catchment_area_km2(watershed_shp: str | Path) -> float:
    """Return catchment area in km2 from watershed polygon.

    Compatibility policy:
    - prefer existing ``AREA`` attribute when present,
    - otherwise compute area directly from geometry.

    Every row of the file counts.
    """
    shp = Path(watershed_shp)
    if not shp.exists():
        raise FileNotFoundError(f"watershed_shp not found: {shp}")
    gdf = gpd.read_file(str(shp))
    if gdf.empty:
        raise ValueError("watershed_shp is empty")
    return catchment_area_m2(gdf, area_field="AREA") / 1_000_000.0
