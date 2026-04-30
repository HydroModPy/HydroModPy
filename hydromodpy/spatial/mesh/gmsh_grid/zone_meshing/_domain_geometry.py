"""Geometry helpers for support-domain loading."""

from __future__ import annotations

from collections.abc import Mapping

from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union


def make_valid_geometry(geometry):
    """Return one cleaned geometry using ``make_valid`` then ``buffer(0)``."""
    if geometry is None:
        return GeometryCollection()
    if geometry.is_empty:
        return geometry
    fixed = make_valid(geometry)
    if fixed.is_empty:
        return fixed
    try:
        repaired = fixed.buffer(0)
    except Exception:  # pragma: no cover - defensive only
        repaired = fixed
    return repaired


def iter_polygon_parts(geometry):
    """Yield polygon parts from polygonal or collection-like geometries."""
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            if not polygon.is_empty:
                yield polygon
        return
    if isinstance(geometry, GeometryCollection):
        for sub_geometry in geometry.geoms:
            yield from iter_polygon_parts(sub_geometry)


def normalize_polygonal_domain_geometry(*, geometry, empty_error: str):
    """Return one cleaned polygonal geometry or raise with a caller-specific message."""
    cleaned = make_valid_geometry(geometry)
    polygons = [polygon for polygon in iter_polygon_parts(cleaned) if float(polygon.area) > 0.0]
    if not polygons:
        raise ValueError(empty_error)
    return unary_union(polygons)


def geometry_to_summary_payload(
    *, geometry, kind: str, extras: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Build the standard summary block returned with a loaded domain payload."""
    bounds = [round(float(v), 6) for v in geometry.bounds]
    payload: dict[str, object] = {
        "domain_kind": str(kind),
        "domain_area": round(float(geometry.area), 12),
        "domain_bounds": bounds,
        "domain_geometry_type": str(geometry.geom_type),
    }
    if extras:
        payload.update({str(key): value for key, value in extras.items()})
    return payload
