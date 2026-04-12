"""Shared I/O helpers for geographic processing."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import rasterio
from pyproj import CRS


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
        shp_path = Path(path_str)
        if not shp_path.exists():
            raise FileNotFoundError(f"Shapefile not found: {shp_path}")
        prj_path = shp_path.with_suffix(".prj")
        wkt = CRS.from_user_input(crs).to_wkt(version="WKT1_ESRI")
        current = prj_path.read_text(encoding="utf-8").strip() if prj_path.exists() else ""
        if current != wkt:
            prj_path.write_text(wkt, encoding="utf-8")


def write_shapefile_without_duplicate_columns(src_path: str | Path, dst_path: str | Path) -> None:
    """Read a shapefile and write it back after dropping duplicate column names."""
    gdf = gpd.read_file(src_path)
    gdf = gdf.loc[:, ~gdf.columns.duplicated()]
    gdf.to_file(dst_path)
