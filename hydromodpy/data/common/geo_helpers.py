"""Spatial helpers: bbox, haversine, nearest station, mask filtering."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from hydromodpy.data.contracts.location import StationLocation


def bbox_hash(bbox: tuple) -> str:
    """Short deterministic hash of a bounding box for filenames."""
    s = f"{bbox[0]:.6f}_{bbox[1]:.6f}_{bbox[2]:.6f}_{bbox[3]:.6f}"
    return hashlib.md5(s.encode()).hexdigest()[:8]


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
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def filter_locations_by_bbox(
    locations: Sequence[StationLocation],
    bbox: tuple,
) -> list[StationLocation]:
    """Keep locations inside bbox."""
    xmin, ymin, xmax, ymax = bbox
    return [loc for loc in locations if xmin <= loc.x <= xmax and ymin <= loc.y <= ymax]


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


def geometry_to_bbox(geometry) -> tuple[float, float, float, float]:
    """Extract (xmin, ymin, xmax, ymax) from a shapely geometry."""
    return geometry.bounds


def filter_locations_by_geometry(
    locations: Sequence[StationLocation],
    geometry,
    *,
    geometry_crs: str = "EPSG:4326",
) -> list[StationLocation]:
    """Keep locations that fall inside a shapely geometry (spatial join).

    Reprojects each location to ``geometry_crs`` before testing, so that
    stations declared in a projected CRS (e.g. Lambert-93 / EPSG:2154) can
    be matched against a mask loaded via
    :func:`~hydromodpy.data.common.source_extent.mask_geometry_wgs84`.
    """
    try:
        from shapely.geometry import Point
    except ImportError as exc:
        raise ImportError("shapely required for geometry filtering. pip install shapely") from exc
    from pyproj import Transformer

    target_crs = str(geometry_crs)
    transformers: dict[str, Transformer] = {}
    kept: list[StationLocation] = []
    for loc in locations:
        src_crs = str(loc.crs) if loc.crs else target_crs
        if src_crs == target_crs:
            x, y = loc.x, loc.y
        else:
            tr = transformers.get(src_crs)
            if tr is None:
                tr = Transformer.from_crs(src_crs, target_crs, always_xy=True)
                transformers[src_crs] = tr
            x, y = tr.transform(loc.x, loc.y)
        # ``intersects`` is more permissive than ``contains`` at boundaries -
        # relevant for outlet stations that land exactly on the watershed
        # boundary after snapping.
        if geometry.intersects(Point(x, y)):
            kept.append(loc)
    return kept


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
