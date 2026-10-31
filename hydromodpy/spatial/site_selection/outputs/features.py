"""The properties and geometries that the vector exports of a selection write.

The GeoJSON files and the GeoPackage and GeoParquet layers carry the same
outlet, basin and observation properties, built here once. One difference is
kept on purpose: a snapped coordinate, a snap distance or an area that does
not exist is ``""`` in GeoJSON, as in the CSV, and ``None`` (null) in the
GeoPackage and GeoParquet layers, whose columns hold one type.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely import make_valid

from hydromodpy.spatial.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_snap_distance_m,
    snapped_outlet_xy,
)
from hydromodpy.spatial.site_selection.outputs.schemas import site_record_from_catchment

REFERENCE_NETWORK_KEYS = (
    "reference_network_source",
    "reference_network_snap_status",
    "reference_network_snap_distance_m",
    "reference_network_original_x",
    "reference_network_original_y",
    "reference_network_x",
    "reference_network_y",
)
"""Outlet attributes that the snap to a reference network writes, exported when set."""

_NUMBERS_EMPTY_IN_CSV = (
    "area_km2",
    "x_outlet_snapped",
    "y_outlet_snapped",
    "outlet_snap_distance_m",
)
"""Site record numbers that the CSV writes as ``""`` when they do not exist."""


def outlet_properties(
    catchment: DelineatedCatchment,
    *,
    selection_id: str,
    region_id: str,
    site_status: str,
    missing: str | None,
) -> dict[str, Any]:
    """Return the properties of the outlet point of *catchment*.

    *missing* is the value written for a snapped coordinate, a snap distance
    or an area that does not exist.
    """
    snapped = snapped_outlet_xy(catchment)
    snap_distance = outlet_snap_distance_m(catchment)
    properties = {
        **_site_properties(
            catchment,
            selection_id=selection_id,
            region_id=region_id,
            site_status=site_status,
            missing=missing,
        ),
        "outlet_geometry_source": "snapped" if snapped is not None else "original",
        "outlet_original_x": catchment.outlet.x,
        "outlet_original_y": catchment.outlet.y,
        "outlet_snap_shp": catchment.outlet_snap_shp or "",
        "x_outlet_snapped": missing if snapped is None else snapped[0],
        "y_outlet_snapped": missing if snapped is None else snapped[1],
        "outlet_snap_distance_m": missing if snap_distance is None else snap_distance,
        "catchment_status": catchment.status,
        "failure_reason": catchment.failure_reason,
        "watershed_shp": catchment.watershed_shp or "",
        "enabled": site_status == "selected",
    }
    for key in REFERENCE_NETWORK_KEYS:
        value = catchment.outlet.attributes.get(key)
        if value is not None:
            properties[key] = value
    return properties


def basin_properties(
    catchment: DelineatedCatchment,
    *,
    watershed_path: Path,
    selection_id: str,
    region_id: str,
    site_status: str,
    missing: str | None,
) -> dict[str, Any]:
    """Return the properties of each part of the basin contour of *catchment*.

    *missing* is the value written for a number of the site record that does
    not exist, as in :func:`outlet_properties`.
    """
    return {
        **_site_properties(
            catchment,
            selection_id=selection_id,
            region_id=region_id,
            site_status=site_status,
            missing=missing,
        ),
        "catchment_status": catchment.status,
        "failure_reason": catchment.failure_reason,
        "watershed_shp": str(watershed_path),
        "enabled": site_status == "selected",
    }


def observation_properties(row: Mapping[str, Any], *, crs: str) -> dict[str, Any]:
    """Return the properties of one observation point from its evidence record."""
    return {
        "site_id": row.get("site_id", ""),
        "observation_type": row.get("observation_type", ""),
        "source_dataset": row.get("source_dataset", ""),
        "feature_id": row.get("feature_id", ""),
        "feature_label": row.get("feature_label", ""),
        "record_start": row.get("record_start"),
        "record_end": row.get("record_end"),
        "record_year_count": row.get("record_year_count"),
        "quality_status": row.get("quality_status", "unknown"),
        "influence_status": row.get("influence_status", "unknown"),
        "distance_to_outlet_km": row.get("distance_to_outlet_km"),
        "distance_to_basin_km": row.get("distance_to_basin_km"),
        "inside_basin": row.get("inside_basin"),
        "observation_crs": crs,
    }


def observation_location(row: Mapping[str, Any]) -> tuple[float, float, str] | None:
    """Return the x, y and CRS of the provider location of an evidence record.

    The location sits in ``evidence_json``, a mapping or its JSON text. A record
    without a readable location gives ``None``.
    """
    evidence_json = row.get("evidence_json")
    if isinstance(evidence_json, str):
        try:
            evidence_json = json.loads(evidence_json)
        except json.JSONDecodeError:
            evidence_json = {}
    if not isinstance(evidence_json, Mapping):
        evidence_json = {}
    location = evidence_json.get("provider_location")
    if not isinstance(location, Mapping):
        return None
    try:
        x = float(location["x"])
        y = float(location["y"])
    except (KeyError, TypeError, ValueError):
        return None
    return x, y, str(location.get("crs") or "")


def placed_observations(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[tuple[Mapping[str, Any], float, float, str]], list[dict[str, str]]]:
    """Split evidence records into the points a layer can place and the skipped ones.

    A point is placed when its provider location is readable and names a CRS
    pyproj reads. Every layer skips the others and records the site, the
    feature and the reason: ``missing_provider_location``,
    ``missing_provider_crs`` or ``unreadable_provider_crs``.
    """
    placed: list[tuple[Mapping[str, Any], float, float, str]] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        location = observation_location(row)
        reason = "missing_provider_location" if location is None else _crs_problem(location[2])
        if reason:
            skipped.append(
                {
                    "site_id": str(row.get("site_id") or ""),
                    "feature_id": str(row.get("feature_id") or ""),
                    "reason": reason,
                }
            )
        else:
            placed.append((row, *location))
    return placed, skipped


def _crs_problem(crs: str) -> str:
    if not crs:
        return "missing_provider_crs"
    try:
        CRS.from_user_input(crs)
    except CRSError:
        return "unreadable_provider_crs"
    return ""


def repair_geometry_for_export(geometry: Any) -> Any:
    """Return a valid version of *geometry*, or ``None`` when nothing is left.

    An invalid geometry goes through ``make_valid``, then ``buffer(0)``. When
    both fail, the geometry is written as it is.
    """
    if geometry is None or geometry.is_empty:
        return None
    if bool(getattr(geometry, "is_valid", True)):
        return geometry
    try:
        repaired = make_valid(geometry)
        if repaired is not None and not repaired.is_empty:
            return repaired
    except Exception:  # noqa: BLE001 - GEOS can fail on a broken ring; buffer(0) comes next.
        pass
    try:
        repaired = geometry.buffer(0)
    except Exception:  # noqa: BLE001 - the export keeps the geometry as read.
        return geometry
    return None if repaired is None or repaired.is_empty else repaired


def _site_properties(
    catchment: DelineatedCatchment,
    *,
    selection_id: str,
    region_id: str,
    site_status: str,
    missing: str | None,
) -> dict[str, Any]:
    record = site_record_from_catchment(
        catchment,
        selection_id=selection_id,
        region_id=region_id,
        site_status=site_status,
    )
    for key in _NUMBERS_EMPTY_IN_CSV:
        if record[key] == "":
            record[key] = missing
    return {
        **record,
        "candidate_id": catchment.outlet.candidate_id,
        "source": catchment.outlet.source,
        "source_feature_id": catchment.outlet.source_feature_id,
        "source_label": catchment.outlet.source_label,
        "outlet_crs": catchment.outlet.crs,
    }


__all__ = [
    "REFERENCE_NETWORK_KEYS",
    "basin_properties",
    "observation_location",
    "observation_properties",
    "outlet_properties",
    "placed_observations",
    "repair_geometry_for_export",
]
