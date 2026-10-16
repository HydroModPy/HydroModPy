"""Geographic facts a run states about itself, and how they are typed.

The extent of a run in WGS84 degrees for the ACDD attributes, the EPSG code
of a CRS token, the description of a vector layer the indexer and the
writer share, the type word a catchment metadata value is stored with, and
the footer every Parquet table of a run carries.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.results.storage.arrow_tables import isoformat_instant
from hydromodpy.results.storage.parquet_schemas import CF_CONVENTIONS, PARQUET_SCHEMA_VERSION

if TYPE_CHECKING:
    from hydromodpy.results.identity import Identity


def python_value_type(value: object) -> str:
    """Return the type word a metadata value is stored with: bool, int, double or string."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    return "string"


def epsg_from_crs(crs: str | None) -> int | None:
    """Return the EPSG code of a CRS token or WKT, or ``None`` when it has none."""
    if not crs:
        return None
    upper = str(crs).upper().strip()
    if upper.startswith("EPSG:"):
        try:
            return int(upper.split(":", 1)[1])
        except ValueError:
            return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None


_GEOMETRY_KINDS = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "linestring",
    "MultiLineString": "linestring",
    "Polygon": "polygon",
    "MultiPolygon": "multipolygon",
}


def geographic_feature_description(gdf: Any) -> tuple[str | None, str, dict[str, Any]]:
    """Return ``(geometry_kind, crs, properties)`` describing a vector layer.

    Shared by the writer and by the indexer, so one GeoParquet file always
    yields the same description whether it was described when written or
    read back from disk afterwards.
    """
    from shapely.ops import unary_union

    union = unary_union([g for g in gdf.geometry if g is not None and not g.is_empty])
    geometry_kind = _GEOMETRY_KINDS.get(union.geom_type, "polygon") if union.geom_type else None
    if gdf.crs is None:
        raise ValueError("Geographic feature CRS is required.")
    crs = gdf.crs.to_string()
    schema_payload = {
        "columns": [str(col) for col in gdf.columns if col != gdf.geometry.name],
        "geometry_kind": geometry_kind,
        "crs": crs,
    }
    properties = {
        "n_features": int(len(gdf)),
        "bbox": [float(value) for value in gdf.total_bounds],
        "geometry_encoding": "WKB",
        "schema_sha256": hashlib.sha256(
            json.dumps(schema_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "geoparquet_version": "1.1.0",
    }
    return geometry_kind, crs, properties


def wgs84_bounds(
    bbox: tuple[float, float, float, float] | None,
    crs: str | None,
) -> dict[str, float] | None:
    """Return ``{lat_min, lat_max, lon_min, lon_max}`` in WGS84 degrees.

    ``None`` whenever the answer cannot be trusted: no extent or projection,
    a projection without an area of use, an extent nowhere near that area,
    or one that crosses the antimeridian. An absent key means unknown.
    """
    if bbox is None or not crs:
        return None
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if len(values) != 4 or any(value != value for value in values):
        return None
    xmin, xmax = min(values[0], values[2]), max(values[0], values[2])
    ymin, ymax = min(values[1], values[3]), max(values[1], values[3])
    try:
        from pyproj import CRS, Transformer

        source = CRS.from_user_input(str(crs))
        area = source.area_of_use
        if area is None:
            return None
        transformer = Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True)
        lon_min, lat_min, lon_max, lat_max = transformer.transform_bounds(
            xmin, ymin, xmax, ymax, densify_pts=21
        )
    except Exception:
        return None
    degrees = (lon_min, lat_min, lon_max, lat_max)
    if any(value != value for value in degrees):
        return None
    if lon_min > lon_max or lat_min > lat_max:
        return None
    if abs(lon_min) > 180.0 or abs(lon_max) > 180.0 or abs(lat_min) > 90.0 or abs(lat_max) > 90.0:
        return None
    west, south, east, north = area.bounds
    if lon_max < west or lon_min > east or lat_max < south or lat_min > north:
        return None
    return {"lat_min": lat_min, "lat_max": lat_max, "lon_min": lon_min, "lon_max": lon_max}


def run_parquet_footer(
    *,
    sim_id: str,
    project: str,
    name: str,
    solver: str | None,
    config_hash: str | None,
    licence: str,
    scientific_objective: str | None,
    doi: str | None,
    identity: Identity,
    created_at: datetime,
    crs_epsg: int | None,
    crs_wkt: str | None,
    bbox: tuple[float, float, float, float] | None,
    period_start: datetime | None,
    period_end: datetime | None,
) -> dict[str, str]:
    """Return the footer every Parquet table of one run carries.

    The run store writes it on the tables a step leaves, the seal on the
    tables of the record. One function, so both halves of a run state the
    same identity, licence and extent.
    """
    written_at = period_end or created_at
    kv: dict[str, str] = {
        "sim_id": sim_id,
        "project": project,
        "name": name,
        "solver": solver or "",
        "config_hash": config_hash or "",
        "hydromodpy_version": HMP_VERSION,
        "hmp.schema_version": PARQUET_SCHEMA_VERSION,
        "Conventions": CF_CONVENTIONS,
        "license": licence,
        "scientific_objective": scientific_objective or "",
        "doi": doi or "",
        "written_at": isoformat_instant(written_at),
    }
    for key, value in identity.as_parquet_metadata().items():
        kv[key.decode("utf-8")] = value.decode("utf-8")
    crs_token = f"EPSG:{crs_epsg}" if crs_epsg is not None else crs_wkt
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        kv["hmp.bbox_xmin"] = str(xmin)
        kv["hmp.bbox_ymin"] = str(ymin)
        kv["hmp.bbox_xmax"] = str(xmax)
        kv["hmp.bbox_ymax"] = str(ymax)
        if crs_token:
            kv["hmp.bbox_crs"] = crs_token
        degrees = wgs84_bounds(bbox, crs_token)
        if degrees is not None:
            kv["geospatial_lon_min"] = str(degrees["lon_min"])
            kv["geospatial_lon_max"] = str(degrees["lon_max"])
            kv["geospatial_lat_min"] = str(degrees["lat_min"])
            kv["geospatial_lat_max"] = str(degrees["lat_max"])
            kv["geospatial_bounds_crs"] = "EPSG:4326"
    if crs_token:
        kv["geospatial_crs"] = crs_token
    if period_start is not None:
        kv["time_coverage_start"] = isoformat_instant(period_start)
    if period_end is not None:
        kv["time_coverage_end"] = isoformat_instant(period_end)
    return kv


__all__ = [
    "epsg_from_crs",
    "geographic_feature_description",
    "python_value_type",
    "run_parquet_footer",
    "wgs84_bounds",
]
