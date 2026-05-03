"""CRS helpers built on :mod:`pyproj` and :mod:`rasterio`.

Centralises coordinate transforms, UTM detection, and polygon-based
filtering so downstream modules never have to reach into ``pyproj``
directly. The PROJ database bootstrap that used to live inline in
``hydromodpy/__init__.py`` is planned to migrate here in a later phase.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio as rio
import xarray as xr
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from shapely.geometry import Point

from hydromodpy.core.io.vector_io import load_shapefile
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def reproject_coord(x_wgs: float, y_wgs: float) -> tuple[str, float, float]:
    """Reproject WGS-84 coordinates to the local UTM zone."""
    lon, lat = x_wgs, y_wgs
    utm_crs_list = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(
            west_lon_degree=lon,
            south_lat_degree=lat,
            east_lon_degree=lon,
            north_lat_degree=lat,
        ),
    )
    utm_crs = CRS.from_epsg(utm_crs_list[0].code).srs
    transformer = Transformer.from_crs("epsg:4326", utm_crs)
    x_utm, y_utm = transformer.transform(lat, lon)
    return utm_crs, x_utm, y_utm


def reproject_shp(raw_shp_path: str, out_shp_path: str, utm_crs: str) -> None:
    """Reproject a shapefile to *utm_crs* (e.g. ``'EPSG:2154'``)."""
    crs_code = utm_crs[5:]
    shp = gpd.read_file(raw_shp_path)
    shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
    shp.to_file(out_shp_path)


def get_centroid_coordinates(gdf: gpd.GeoDataFrame) -> tuple:
    """Return (lon, lat) centroid of the first geometry in *gdf*."""
    if gdf is None:
        logger.error("GeoDataFrame input is None")
        return None, None
    if gdf.empty:
        logger.error("GeoDataFrame contains no features")
        return None, None
    if gdf.crs is None:
        logger.error("GeoDataFrame has no CRS defined")
        return None, None
    try:
        gdf = gdf.to_crs("EPSG:2056")
        gdf["geometry"] = gdf.geometry.centroid
        gdf = gdf.to_crs("EPSG:4326")
        point = gdf.geometry.iloc[0]
        return point.x, point.y
    except Exception:
        logger.exception("Failed computing centroid coordinates")
        return None, None


def transform_coordinates(dem_file_path: str, from_crs: str, to_crs: str) -> list:
    """Convert all DEM pixel coordinates from *from_crs* to *to_crs*."""
    try:
        dem_dataset = rio.open(dem_file_path)
        transform = dem_dataset.transform
        width, height = dem_dataset.width, dem_dataset.height
        transformer = Transformer.from_crs(from_crs, to_crs, always_xy=True)

        coordinates = []
        for row in range(height):
            for col in range(width):
                x, y = transform * (col, row)
                lon, lat = transformer.transform(x, y)
                coordinates.append((lon, lat))
        return coordinates
    except Exception:
        logger.exception("Failed processing DEM raster %s", dem_file_path)
        return []


def filter_coordinates_by_shape(coordinates: list, shapefile_path: str, target_crs: str) -> list:
    """Keep only coordinates that fall within the shapefile polygon."""
    try:
        gdf = load_shapefile(shapefile_path)
        if gdf is None:
            return []
        polygon = gdf.to_crs(target_crs).unary_union
        return [pt for pt in coordinates if polygon.covers(Point(pt))]
    except Exception:
        logger.exception("Failed filtering coordinates with shapefile %s", shapefile_path)
        return []


def select_nearest_point(ds: xr.Dataset, lon: float, lat: float) -> xr.Dataset | None:
    """Select the nearest grid point in *ds*."""
    if lon is not None and lat is not None:
        return ds.sel(longitude=lon, latitude=lat, method="nearest")
    return None


def select_within_polygon_points(ds: xr.Dataset, gdf: gpd.GeoDataFrame) -> xr.Dataset:
    """Mask *ds* to keep only points inside the *gdf* polygon."""
    try:
        polygon = gdf.unary_union
        lons = ds.longitude.values
        lats = ds.latitude.values
        LON, LAT = np.meshgrid(lons, lats)
        mask = np.zeros(LON.shape, dtype=bool)
        for i in range(LON.shape[0]):
            for j in range(LON.shape[1]):
                mask[i, j] = polygon.contains(Point(LON[i, j], LAT[i, j]))
        return ds.where(mask, drop=True)
    except Exception:
        logger.exception("Failed selecting dataset points within polygon")
        return ds


def convert_units(df, var_key: str):
    """Apply unit conversions for precipitation, temperature, radiation."""
    if var_key == "precipitation":
        df = df * 1000.0
    elif var_key == "temperature":
        df = df - 273.15
    elif var_key == "radiation":
        df = df * 1e-6
    return df


__all__ = [
    "reproject_coord",
    "reproject_shp",
    "get_centroid_coordinates",
    "transform_coordinates",
    "filter_coordinates_by_shape",
    "select_nearest_point",
    "select_within_polygon_points",
    "convert_units",
]
