"""Spatial helpers: bbox, haversine, nearest station, mask filtering."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from hydromodpy.data_managers.contracts.location import StationLocation


def bbox_contains(outer: tuple, inner: tuple) -> bool:
    """True if outer bbox fully contains inner. Both are (xmin, ymin, xmax, ymax)."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km (WGS84)."""
    R = 6371.0
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def filter_locations_by_bbox(
    locations: Sequence[StationLocation],
    bbox: tuple,
) -> list[StationLocation]:
    """Keep locations inside bbox."""
    xmin, ymin, xmax, ymax = bbox
    return [
        loc for loc in locations
        if xmin <= loc.x <= xmax and ymin <= loc.y <= ymax
    ]


def nearest_location(
    x: float,
    y: float,
    locations: Sequence[StationLocation],
    *,
    crs_is_geographic: bool = True,
) -> StationLocation | None:
    """Return closest location to (x, y)."""
    if not locations:
        return None
    if crs_is_geographic:
        return min(locations, key=lambda loc: haversine_km(x, y, loc.x, loc.y))
    return min(locations, key=lambda loc: math.hypot(loc.x - x, loc.y - y))


def load_mask_geometry(path: Path):
    """Load a spatial mask from vector (SHP/GPKG/GeoJSON) or raster (TIF).

    Returns a shapely geometry (union of all features for vector,
    convex hull of valid cells for raster).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Mask file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".shp", ".gpkg", ".geojson"):
        return _load_mask_from_vector(path)
    elif suffix in (".tif", ".tiff"):
        return _load_mask_from_raster(path)
    else:
        raise ValueError(f"Unsupported mask format: {suffix}. Use SHP, GPKG, GeoJSON, or TIF.")


def _load_mask_from_vector(path: Path):
    """Load mask geometry from vector file (union of all features)."""
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise ImportError("geopandas required for vector mask. pip install geopandas") from exc
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Empty vector file: {path}")
    if hasattr(gdf.geometry, "union_all"):
        return gdf.geometry.union_all()
    return gdf.geometry.unary_union


def _load_mask_from_raster(path: Path):
    """Load mask geometry from raster (convex hull of valid cells)."""
    try:
        import rasterio
        from rasterio.features import shapes
        from shapely.geometry import shape
        from shapely.ops import unary_union
    except ImportError as exc:
        raise ImportError("rasterio and shapely required for raster mask. pip install rasterio shapely") from exc

    with rasterio.open(path) as src:
        data = src.read(1)
        mask = data != src.nodata if src.nodata is not None else data != 0
        geoms = [shape(geom) for geom, val in shapes(mask.astype("uint8"), transform=src.transform) if val == 1]
        if not geoms:
            raise ValueError(f"No valid cells in raster mask: {path}")
        return unary_union(geoms).convex_hull


def geometry_to_bbox(geometry) -> tuple[float, float, float, float]:
    """Extract (xmin, ymin, xmax, ymax) from a shapely geometry."""
    return geometry.bounds


def filter_locations_by_geometry(
    locations: Sequence[StationLocation],
    geometry,
) -> list[StationLocation]:
    """Keep locations that fall inside a shapely geometry (spatial join)."""
    try:
        from shapely.geometry import Point
    except ImportError as exc:
        raise ImportError("shapely required for geometry filtering. pip install shapely") from exc

    return [
        loc for loc in locations
        if geometry.contains(Point(loc.x, loc.y))
    ]


def expand_bbox(
    bbox: tuple[float, float, float, float],
    radius_km: float,
) -> tuple[float, float, float, float]:
    """Expand bbox by radius_km in all directions (approximate, WGS84)."""
    xmin, ymin, xmax, ymax = bbox
    # ~111 km per degree latitude, longitude varies with latitude
    lat_mid = (ymin + ymax) / 2
    deg_lat = radius_km / 111.0
    deg_lon = radius_km / (111.0 * math.cos(math.radians(lat_mid)))
    return (xmin - deg_lon, ymin - deg_lat, xmax + deg_lon, ymax + deg_lat)
