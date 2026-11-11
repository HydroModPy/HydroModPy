"""CRS helpers built on :mod:`pyproj` and :mod:`rasterio`.

Centralizes coordinate transforms, UTM detection, polygon-based filtering
and the CRS stamp a producer writes onto its own output, so downstream
modules never have to reach into ``pyproj`` directly. ``ensure_crs`` lives
here rather than beside one producer because every layer that writes a
raster or a shapefile needs it, including engines that must not import a
sibling package to find it. The PROJ database bootstrap that used to live inline in
``hydromodpy/__init__.py`` is planned to migrate here in a later phase.

``to_mesh_crs`` brings a vector layer into the frame of a mesh before an
overlay. It sits here so that any layer that overlays vector data on cells
reads it without importing the mesh package.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import rasterio as rio
import shapely
import xarray as xr
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import Point

from hydromodpy.core.io.vector_io import load_shapefile
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

logger = get_logger(__name__)

CrsLike = str | int | CRS
"""A CRS as a caller names it: an EPSG code, a WKT or PROJ string, or a ``pyproj.CRS``."""


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
        polygon = gdf.to_crs(target_crs).union_all()
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
        LON, LAT = np.meshgrid(ds.longitude.values, ds.latitude.values)
        mask = shapely.contains_xy(gdf.union_all(), LON, LAT)
        return ds.where(xr.DataArray(mask, dims=("latitude", "longitude")), drop=True)
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


def ensure_crs(path: str | Path, crs: str | None) -> None:
    """Write *crs* onto a GeoTIFF or a shapefile that carries none.

    Two file kinds, two mechanisms. A GeoTIFF is reopened in update mode and
    only its CRS tag is rewritten, so the band data is never re-encoded. A
    shapefile gets its sidecar ``.prj`` written in WKT1 ESRI, the dialect the
    format's readers expect, and the ``.shp`` itself is left untouched: reading
    and rewriting the vector to set a CRS would renumber nothing but would
    round the coordinates through geopandas.

    A ``None`` *crs* is a caller that has nothing to declare, and declaring
    nothing is not an error.
    """
    if crs is None:
        return
    path_str = str(path)
    if path_str.lower().endswith(".tif"):
        with rio.open(path_str, "r+") as dst:
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


def same_crs(left: str, right: str) -> bool:
    """Tell whether two CRS labels name the same frame.

    Labels equal up to case and outer spaces match at once. Otherwise both are
    read by pyproj, and a label pyproj cannot read matches nothing. Two CRS
    match when pyproj finds them equal up to the order of their axes, or when
    it identifies both as the same EPSG code. A Lambert-93 written in proj4
    without its datum is so EPSG:2154.
    """
    if left.strip().upper() == right.strip().upper():
        return True
    try:
        left_crs, right_crs = CRS.from_user_input(left), CRS.from_user_input(right)
    except CRSError:
        return False
    if left_crs.equals(right_crs, ignore_axis_order=True):
        return True
    left_epsg = left_crs.to_epsg()
    return left_epsg is not None and left_epsg == right_crs.to_epsg()


def crs_text(crs: object | None) -> str | None:
    """Return the CRS a raster declares as text, or ``None`` when it declares none.

    *crs* is the ``crs`` attribute of an open rasterio dataset. An empty CRS
    counts as no CRS.
    """
    if crs is None or not crs:
        return None
    return crs.to_string()


RFC7946_CRS = "OGC:CRS84"
"""The CRS of every GeoJSON coordinate (RFC 7946): WGS 84 longitude, then latitude."""


def to_mesh_crs(
    geometries: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
) -> list[BaseGeometry]:
    """Return the non-empty geometries expressed in the mesh CRS."""
    from shapely.ops import transform

    target = require_crs(mesh_crs, "mesh_crs")
    source = require_crs(geometry_crs, "geometry_crs")
    parts = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not parts or source.equals(target):
        return parts
    project = Transformer.from_crs(source, target, always_xy=True).transform
    return [transform(project, geometry) for geometry in parts]


def require_crs(crs_like: CrsLike | None, name: str) -> CRS:
    """Coerce one CRS argument, refusing the missing case."""
    if crs_like is None or (isinstance(crs_like, str) and not crs_like.strip()):
        raise ValueError(
            f"vector_cell_mask needs an explicit {name}: a mesh stores bare coordinates, "
            "so without both frames the overlay silently compares two different ones."
        )
    return CRS.from_user_input(crs_like)


def _coerce_crs(crs_like: object | None) -> CRS | None:
    """Read a CRS label, or return None for no label or one pyproj cannot read."""
    if crs_like is None or (isinstance(crs_like, str) and not crs_like.strip()):
        return None
    try:
        return CRS.from_user_input(crs_like)
    except (CRSError, TypeError, ValueError):
        return None


def _bounds_look_geographic(gdf: gpd.GeoDataFrame) -> bool:
    """Tell whether the bounds of ``gdf`` fit in longitude and latitude ranges."""
    if gdf is None or gdf.empty:
        return True
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    return bool(
        np.isfinite([minx, miny, maxx, maxy]).all()
        and minx >= -180.0
        and maxx <= 180.0
        and miny >= -90.0
        and maxy <= 90.0
    )


def project_gdf_for_metric_operations(
    gdf: gpd.GeoDataFrame | None,
    *,
    fallback_crs: CrsLike | None = None,
) -> gpd.GeoDataFrame | None:
    """Return ``gdf`` in a projected CRS, so lengths and areas come out in meters.

    A frame without a CRS takes ``fallback_crs``. So does a frame labelled
    geographic whose coordinates cannot be degrees. A projected frame is
    returned as is. A geographic one goes to its UTM zone, else to
    ``fallback_crs`` when that one is projected.
    """
    if gdf is None or gdf.empty:
        return gdf

    out = gdf.copy()
    source_crs = _coerce_crs(out.crs)
    fallback = _coerce_crs(fallback_crs)

    if fallback is not None and (
        source_crs is None or (source_crs.is_geographic and not _bounds_look_geographic(out))
    ):
        out = out.set_crs(fallback, allow_override=True)
        source_crs = fallback

    if source_crs is None or source_crs.is_projected:
        return out

    try:
        target = out.estimate_utm_crs()
    except (RuntimeError, ValueError, CRSError):
        target = None
    if target is None and fallback is not None and fallback.is_projected:
        target = fallback
    return out if target is None else out.to_crs(target)


def measure_linework_length_m(
    gdf: gpd.GeoDataFrame | None,
    *,
    fallback_crs: CrsLike | None = None,
) -> float:
    """Return the total line length of ``gdf`` in meters, in one metric CRS."""
    if gdf is None or gdf.empty:
        return 0.0
    metric_gdf = project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs)
    return float(np.sum(np.asarray(metric_gdf.length, dtype=float)))


__all__ = [
    "CrsLike",
    "RFC7946_CRS",
    "crs_text",
    "ensure_crs",
    "measure_linework_length_m",
    "project_gdf_for_metric_operations",
    "same_crs",
    "require_crs",
    "to_mesh_crs",
    "get_centroid_coordinates",
    "transform_coordinates",
    "filter_coordinates_by_shape",
    "select_nearest_point",
    "select_within_polygon_points",
    "convert_units",
]
