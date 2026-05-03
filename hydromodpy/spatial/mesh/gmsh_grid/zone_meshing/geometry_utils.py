"""Low-level Shapely utilities shared by zone-meshing preprocessing."""

from __future__ import annotations

import numpy as np
from shapely import make_valid
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
)


def as_metric_tolerance(raw: float | None, *, default: float = 0.0) -> float:
    """Normalize one optional metric tolerance used during Shapely cleaning."""
    if raw is None:
        return float(default)
    value = float(raw)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError("tolerances must be finite and >= 0")
    return value


def is_invalid_nonempty_geometry(geometry) -> bool:
    """Return whether one geometry is both non-empty and invalid."""
    if geometry is None:
        return False
    if getattr(geometry, "is_empty", False):
        return False
    return bool(not getattr(geometry, "is_valid", True))


def make_valid_geometry(geometry):
    """Repair one geometry and return a polygon/collection-safe result."""
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


def make_valid_linework(geometry):
    """Repair linework without forcing polygon-style buffering."""
    if geometry is None:
        return GeometryCollection()
    if geometry.is_empty:
        return geometry
    return make_valid(geometry)


def iter_polygon_parts(geometry):
    """Yield polygon parts from polygon, multipolygon or collection inputs."""
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


def iter_line_parts(geometry):
    """Yield line parts from line, multiline or collection inputs."""
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        yield geometry
        return
    if isinstance(geometry, MultiLineString):
        for line in geometry.geoms:
            if not line.is_empty:
                yield line
        return
    if isinstance(geometry, GeometryCollection):
        for sub_geometry in geometry.geoms:
            yield from iter_line_parts(sub_geometry)


__all__ = [
    "as_metric_tolerance",
    "is_invalid_nonempty_geometry",
    "iter_line_parts",
    "iter_polygon_parts",
    "make_valid_geometry",
    "make_valid_linework",
]
