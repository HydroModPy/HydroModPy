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


def resolve_delineation_backend(backend: object | None = None) -> object:
    """Return the injected backend or the default delineation registry entry."""
    if backend is not None:
        return backend
    from hydromodpy.spatial.delineation import get_backend

    return get_backend()


def backend_has_callables(backend: object, component_name: str, *method_names: str) -> bool:
    """Return true when one backend component exposes all named methods."""
    component = getattr(backend, component_name, None)
    if component is None:
        return False
    return all(callable(getattr(component, method_name, None)) for method_name in method_names)


def read_raster_data_and_meta(path: str | Path) -> tuple:
    """Read raster data + metadata from backend cache or disk.

    Returns ``(data, transform_gdal, nodata, crs_string)``.
    ``transform_gdal`` is a 6-element GDAL-style geotransform tuple.
    """

    path_str = str(path)
    backend = resolve_delineation_backend()
    raster_backend = getattr(backend, "raster", None)
    if raster_backend is not None and backend_has_callables(
        backend,
        "raster",
        "get_cached_raster_numpy",
        "get_cached_raster_metadata",
    ):
        data = raster_backend.get_cached_raster_numpy(path_str)
        if data is not None:
            meta = raster_backend.get_cached_raster_metadata(path_str)
            t = meta["transform"]  # (res_x, 0, west, 0, -res_y, north)
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
