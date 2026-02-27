"""Shared I/O helpers for geographic processing."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import rasterio


def ensure_crs(path: str | Path, crs: str | None) -> None:
    """Ensure a raster or shapefile has the given CRS metadata."""
    if crs is None:
        return
    path_str = str(path)
    if path_str.lower().endswith(".tif"):
        with rasterio.open(path_str, "r+") as dst:
            dst.crs = crs
        return
    if path_str.lower().endswith(".shp"):
        gdf = gpd.read_file(path_str)
        gdf = gdf.set_crs(crs, allow_override=True)
        gdf.to_file(path_str)


def write_shapefile_without_duplicate_columns(src_path: str | Path, dst_path: str | Path) -> None:
    """Read a shapefile and write it back after dropping duplicate column names."""
    gdf = gpd.read_file(src_path)
    gdf = gdf.loc[:, ~gdf.columns.duplicated()]
    gdf.to_file(dst_path)
