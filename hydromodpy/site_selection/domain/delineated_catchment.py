"""The delineated catchment of one candidate outlet and its outlet coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS, Transformer

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.site_selection.domain.candidate_outlet import CandidateOutlet

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
    """Return the snapped outlet coordinates when the delineation wrote them.

    The point comes back in the CRS of the outlet. A GeoJSON file without a
    ``crs`` member holds WGS 84 lon/lat (RFC 7946) and is reprojected.
    """

    if not catchment.outlet_snap_shp:
        return None
    return _read_first_point_xy(Path(catchment.outlet_snap_shp), crs=catchment.outlet.crs)


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


def _read_first_point_xy(path: Path, *, crs: str) -> tuple[float, float] | None:
    if not path.is_file():
        return None
    try:
        frame = gpd.read_file(str(path))
    except Exception:
        return None
    point = _first_point(frame)
    if point is None or frame.crs is None or not crs:
        return point
    x, y = point
    if frame.crs.is_geographic and not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
        raise DataContractViolation(
            f"{path}: the snapped outlet ({x}, {y}) is not a longitude and latitude, yet the "
            f"file is in {frame.crs.to_string()}; a GeoJSON without a crs member holds WGS 84 "
            "lon/lat (RFC 7946)."
        )
    target = CRS.from_user_input(crs)
    if frame.crs == target:
        return point
    target_x, target_y = Transformer.from_crs(frame.crs, target, always_xy=True).transform(x, y)
    return float(target_x), float(target_y)


def _first_point(frame: gpd.GeoDataFrame) -> tuple[float, float] | None:
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
