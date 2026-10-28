"""The delineated catchment of one candidate outlet and its outlet coordinates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet

__all__ = [
    "DelineatedCatchment",
    "outlet_display_xy",
    "outlet_snap_distance_m",
    "snapped_outlet_xy",
]


@dataclass(frozen=True)
class DelineatedCatchment:
    """Delineation result for one candidate outlet."""

    site_id: str
    outlet: CandidateOutlet
    outlet_shp: str | None = None
    outlet_snap_shp: str | None = None
    watershed_tif: str | None = None
    watershed_shp: str | None = None
    area_km2: float | None = None
    status: str = "delineated"
    failure_reason: str = ""

    def to_record(self) -> dict[str, Any]:
        """Return a CSV/parquet-friendly mapping."""

        return {
            "site_id": self.site_id,
            "candidate_id": self.outlet.candidate_id,
            "x_outlet": self.outlet.x,
            "y_outlet": self.outlet.y,
            "outlet_crs": self.outlet.crs,
            "outlet_shp": self.outlet_shp,
            "outlet_snap_shp": self.outlet_snap_shp,
            "watershed_tif": self.watershed_tif,
            "watershed_shp": self.watershed_shp,
            "area_km2": self.area_km2,
            "status": self.status,
            "failure_reason": self.failure_reason,
        }


def snapped_outlet_xy(catchment: DelineatedCatchment) -> tuple[float, float] | None:
    """Return the snapped outlet coordinates when the delineation wrote them."""

    if not catchment.outlet_snap_shp:
        return None
    return _read_first_point_xy(Path(catchment.outlet_snap_shp))


def outlet_display_xy(catchment: DelineatedCatchment) -> tuple[float, float]:
    """Return the outlet coordinate to display on maps and spatial exports."""

    return snapped_outlet_xy(catchment) or (float(catchment.outlet.x), float(catchment.outlet.y))


def outlet_snap_distance_m(catchment: DelineatedCatchment) -> float | None:
    """Distance between original candidate outlet and snapped outlet in projected metres."""

    snapped = snapped_outlet_xy(catchment)
    if snapped is None:
        return None
    return math.hypot(
        snapped[0] - float(catchment.outlet.x), snapped[1] - float(catchment.outlet.y)
    )


def _read_first_point_xy(path: Path) -> tuple[float, float] | None:
    if not path.is_file():
        return None
    if path.suffix.lower() in {".geojson", ".json"}:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return _first_point_xy_from_geojson(payload)
    try:
        frame = gpd.read_file(str(path))
    except Exception:
        return None
    for geometry in frame.geometry:
        if geometry is None or geometry.is_empty:
            continue
        if geometry.geom_type == "Point":
            return float(geometry.x), float(geometry.y)
        if geometry.geom_type == "MultiPoint":
            point = next(iter(geometry.geoms), None)
            if point is not None:
                return float(point.x), float(point.y)
    return None


def _first_point_xy_from_geojson(payload: object) -> tuple[float, float] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list):
            return None
        for feature in features:
            if not isinstance(feature, dict):
                continue
            point = _point_xy_from_geometry(feature.get("geometry"))
            if point is not None:
                return point
        return None
    if payload.get("type") == "Feature":
        return _point_xy_from_geometry(payload.get("geometry"))
    return _point_xy_from_geometry(payload)


def _point_xy_from_geometry(geometry: object) -> tuple[float, float] | None:
    if not isinstance(geometry, dict):
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point" and isinstance(coordinates, list | tuple) and len(coordinates) >= 2:
        try:
            return float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError):
            return None
    if geometry_type == "MultiPoint" and isinstance(coordinates, list) and coordinates:
        first = coordinates[0]
        if isinstance(first, list | tuple) and len(first) >= 2:
            try:
                return float(first[0]), float(first[1])
            except (TypeError, ValueError):
                return None
    return None
