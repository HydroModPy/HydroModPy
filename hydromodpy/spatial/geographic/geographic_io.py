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


def read_raster_data_and_meta(path: str | Path) -> tuple:
    """Read raster data + metadata from whitebox cache or disk.

    Returns ``(data, transform_gdal, nodata, crs_string)``.
    ``transform_gdal`` is a 6-element GDAL-style geotransform tuple.
    """
    import numpy as np

    path_str = str(path)
    from hydromodpy.core.backends import get_whitebox_backend
    wb = get_whitebox_backend()
    data = wb.get_cached_raster_numpy(path_str)
    if data is not None:
        meta = wb.get_cached_raster_metadata(path_str)
        t = meta["transform"]  # (res_x, 0, west, 0, -res_y, north)
        # Convert to GDAL geotransform: (west, res_x, 0, north, 0, -res_y)
        gdal_transform = (t[2], t[0], 0.0, t[5], 0.0, -t[4])
        nodata = meta["nodata"]
        crs = str(meta.get("crs", ""))
        return data, gdal_transform, nodata, crs

    with rasterio.open(path_str) as src:
        data = src.read(1)
        gdal_transform = src.transform.to_gdal()
        nodata = src.nodata
        crs = str(src.crs) if src.crs else ""
    return data, gdal_transform, nodata, crs
