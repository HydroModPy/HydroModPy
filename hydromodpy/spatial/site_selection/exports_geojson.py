"""GeoJSON exports for site-selection spatial review artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.delineation import (
    DelineatedCatchment,
    outlet_display_xy,
    outlet_snap_distance_m,
    snapped_outlet_xy,
)
from hydromodpy.spatial.site_selection.schemas import site_record_from_catchment


def write_outlets_geojson(
    path: str | Path,
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str = "",
    site_status: str,
) -> Path:
    """Write a lightweight point GeoJSON for selected or rejected outlets."""

    materialized = list(catchments)
    crs_values = sorted({catchment.outlet.crs for catchment in materialized})
    features = []
    for catchment in materialized:
        display_x, display_y = outlet_display_xy(catchment)
        snapped = snapped_outlet_xy(catchment)
        snap_distance = outlet_snap_distance_m(catchment)
        properties = {
            **site_record_from_catchment(
                catchment,
                selection_id=selection_id,
                region_id=region_id,
                site_status=site_status,
            ),
            "candidate_id": catchment.outlet.candidate_id,
            "source": catchment.outlet.source,
            "source_feature_id": catchment.outlet.source_feature_id,
            "source_label": catchment.outlet.source_label,
            "outlet_crs": catchment.outlet.crs,
            "outlet_geometry_source": "snapped" if snapped is not None else "original",
            "outlet_original_x": catchment.outlet.x,
            "outlet_original_y": catchment.outlet.y,
            "outlet_snap_shp": catchment.outlet_snap_shp or "",
            "x_outlet_snapped": "" if snapped is None else snapped[0],
            "y_outlet_snapped": "" if snapped is None else snapped[1],
            "outlet_snap_distance_m": "" if snap_distance is None else snap_distance,
            "catchment_status": catchment.status,
            "failure_reason": catchment.failure_reason,
            "watershed_shp": catchment.watershed_shp or "",
        }
        for key in (
            "reference_network_source",
            "reference_network_snap_status",
            "reference_network_snap_distance_m",
            "reference_network_original_x",
            "reference_network_original_y",
            "reference_network_x",
            "reference_network_y",
        ):
            value = catchment.outlet.attributes.get(key)
            if value is not None:
                properties[key] = value
        properties["enabled"] = site_status == "selected"
        features.append(
            {
                "type": "Feature",
                "id": catchment.site_id,
                "geometry": {
                    "type": "Point",
                    "coordinates": [display_x, display_y],
                },
                "properties": properties,
            }
        )

    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_coordinate_crs": crs_values[0] if len(crs_values) == 1 else "mixed",
        "features": features,
    }
    return _write_geojson(path, collection)


def write_basins_geojson(
    path: str | Path,
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str = "",
    site_status: str,
) -> Path:
    """Write basin contour geometries when delineated vector files exist."""

    materialized = list(catchments)
    features: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    crs_values: set[str] = set()
    for catchment in materialized:
        watershed_path = Path(catchment.watershed_shp or "")
        if not catchment.watershed_shp or not watershed_path.is_file():
            skipped.append(
                {
                    "site_id": catchment.site_id,
                    "reason": "missing_watershed_vector",
                    "watershed_shp": catchment.watershed_shp or "",
                }
            )
            continue
        try:
            basin_features, crs_label = _features_from_watershed_vector(
                watershed_path,
                catchment=catchment,
                selection_id=selection_id,
                region_id=region_id,
                site_status=site_status,
            )
        except Exception as exc:  # noqa: BLE001 - keep export robust and auditable.
            skipped.append(
                {
                    "site_id": catchment.site_id,
                    "reason": f"read_failed: {exc}",
                    "watershed_shp": str(watershed_path),
                }
            )
            continue
        features.extend(basin_features)
        if crs_label:
            crs_values.add(crs_label)

    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_geometry_role": "basin_contours",
        "hydromodpy_coordinate_crs": _single_or_mixed(crs_values),
        "hydromodpy_skipped_basins": skipped,
        "features": features,
    }
    return _write_geojson(path, collection)


def write_observation_points_geojson(
    path: str | Path,
    evidence: Iterable[object],
) -> Path:
    """Write observation locations from normalized observation evidence."""

    rows = [
        item.to_record() if hasattr(item, "to_record") else dict(item)
        for item in evidence
    ]
    features: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    crs_values: set[str] = set()
    for row in rows:
        location = _observation_location(row)
        if location is None:
            skipped.append(
                {
                    "site_id": str(row.get("site_id") or ""),
                    "feature_id": str(row.get("feature_id") or ""),
                    "reason": "missing_provider_location",
                }
            )
            continue
        x, y, crs = location
        if crs:
            crs_values.add(crs)
        features.append(
            {
                "type": "Feature",
                "id": f"{row.get('site_id', '')}:{row.get('feature_id', '')}",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": {
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
                },
            }
        )

    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_geometry_role": "observation_points",
        "hydromodpy_coordinate_crs": _single_or_mixed(crs_values),
        "hydromodpy_skipped_observations": skipped,
        "features": features,
    }
    return _write_geojson(path, collection)


def _write_geojson(path: str | Path, collection: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(dict(collection), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _features_from_watershed_vector(
    path: Path,
    *,
    catchment: DelineatedCatchment,
    selection_id: str,
    region_id: str,
    site_status: str,
) -> tuple[list[dict[str, Any]], str]:
    import geopandas as gpd

    frame = gpd.read_file(str(path))
    if frame.empty:
        return [], _crs_label(frame.crs)
    properties = {
        **site_record_from_catchment(
            catchment,
            selection_id=selection_id,
            region_id=region_id,
            site_status=site_status,
        ),
        "candidate_id": catchment.outlet.candidate_id,
        "source": catchment.outlet.source,
        "source_feature_id": catchment.outlet.source_feature_id,
        "source_label": catchment.outlet.source_label,
        "outlet_crs": catchment.outlet.crs,
        "catchment_status": catchment.status,
        "failure_reason": catchment.failure_reason,
        "watershed_shp": str(path),
    }
    properties["enabled"] = site_status == "selected"
    features = []
    for index, geometry in enumerate(frame.geometry):
        geometry = _repair_geometry_for_export(geometry)
        if geometry is None or geometry.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "id": f"{catchment.site_id}:{index}",
                "geometry": geometry.__geo_interface__,
                "properties": properties,
            }
        )
    return features, _crs_label(frame.crs)


def _repair_geometry_for_export(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if bool(getattr(geometry, "is_valid", True)):
        return geometry
    try:
        from shapely import make_valid
    except ImportError:  # pragma: no cover - depends on Shapely version.
        try:
            from shapely.validation import make_valid
        except ImportError:
            make_valid = None
    if make_valid is not None:
        try:
            repaired = make_valid(geometry)
            if repaired is not None and not repaired.is_empty:
                return repaired
        except Exception:
            pass
    try:
        repaired = geometry.buffer(0)
    except Exception:
        return geometry
    return None if repaired is None or repaired.is_empty else repaired


def _observation_location(row: Mapping[str, Any]) -> tuple[float, float, str] | None:
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


def _crs_label(value: object) -> str:
    return "" if value is None else str(value)


def _single_or_mixed(values: set[str]) -> str:
    clean = {value for value in values if value}
    if not clean:
        return ""
    if len(clean) == 1:
        return next(iter(clean))
    return "mixed"


__all__ = [
    "write_basins_geojson",
    "write_observation_points_geojson",
    "write_outlets_geojson",
]
