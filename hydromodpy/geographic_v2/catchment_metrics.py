"""Catchment geometry metrics used by the geographic V2 pipeline."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np


def compute_catchment_area_km2(watershed_shp: str | Path) -> float:
    """Compute catchment area in km2 from a watershed shapefile.

    Compatibility rule:
    - prefer legacy ``AREA`` attribute when present,
    - fallback to geometric area from polygon geometry.
    """
    # Step 1 - Validate and read watershed polygon.
    shp = Path(watershed_shp)
    if not shp.exists():
        raise FileNotFoundError(f"watershed_shp not found: {shp}")
    gdf = gpd.read_file(str(shp))
    if gdf.empty:
        raise ValueError("watershed_shp is empty")

    # Step 2 - Return area in square kilometers.
    try:
        area_km2 = float(np.abs(gdf.AREA.iloc[0]) / 1_000_000.0)
    except Exception:
        area_km2 = float(np.abs(gdf.area.iloc[0]) / 1_000_000.0)
    return area_km2
