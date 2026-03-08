"""Compute scalar metrics from catchment polygons.

At this stage, the module exposes catchment area in km2 with a compatibility
policy aligned on legacy workflows.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np


def compute_catchment_area_km2(watershed_shp: str | Path) -> float:
    """Return catchment area in km2 from watershed polygon.

    Compatibility policy:
    - prefer legacy ``AREA`` attribute when present,
    - otherwise compute area directly from geometry.
    """
    shp = Path(watershed_shp)
    if not shp.exists():
        raise FileNotFoundError(f"watershed_shp not found: {shp}")
    gdf = gpd.read_file(str(shp))
    if gdf.empty:
        raise ValueError("watershed_shp is empty")

    try:
        area_km2 = float(np.abs(gdf.AREA.iloc[0]) / 1_000_000.0)
    except Exception:
        area_km2 = float(np.abs(gdf.area.iloc[0]) / 1_000_000.0)
    return area_km2
