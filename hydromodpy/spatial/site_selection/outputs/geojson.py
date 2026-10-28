"""GeoJSON exports for site-selection spatial review artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.io.crs import geojson_crs_member
from hydromodpy.spatial.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_display_xy,
)
from hydromodpy.spatial.site_selection.domain.export_values import single_or_mixed
from hydromodpy.spatial.site_selection.domain.watershed import read_watershed
from hydromodpy.spatial.site_selection.outputs.features import (
    basin_properties,
    observation_location,
    observation_properties,
    outlet_properties,
    repair_geometry_for_export,
)


def write_geojson(path: str | Path, collection: Mapping[str, Any]) -> Path:
    """Write *collection* to *path* as indented JSON with sorted keys, in ASCII."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(dict(collection), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


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
        features.append(
            {
                "type": "Feature",
                "id": catchment.site_id,
                "geometry": {
                    "type": "Point",
                    "coordinates": [display_x, display_y],
                },
                "properties": outlet_properties(
                    catchment,
                    selection_id=selection_id,
                    region_id=region_id,
                    site_status=site_status,
                    missing="",
                ),
            }
        )

    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_coordinate_crs": crs_values[0] if len(crs_values) == 1 else "mixed",
        **geojson_crs_member(crs_values[0] if len(crs_values) == 1 else "mixed"),
        "features": features,
    }
    return write_geojson(path, collection)


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
        "hydromodpy_coordinate_crs": single_or_mixed(crs_values),
        **geojson_crs_member(single_or_mixed(crs_values)),
        "hydromodpy_skipped_basins": skipped,
        "features": features,
    }
    return write_geojson(path, collection)


def write_observation_points_geojson(
    path: str | Path,
    evidence: Iterable[object],
) -> Path:
    """Write observation locations from normalized observation evidence."""

    rows = [item.to_record() if hasattr(item, "to_record") else dict(item) for item in evidence]
    features: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    crs_values: set[str] = set()
    for row in rows:
        location = observation_location(row)
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
                "properties": observation_properties(row, crs=crs),
            }
        )

    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_geometry_role": "observation_points",
        "hydromodpy_coordinate_crs": single_or_mixed(crs_values),
        **geojson_crs_member(single_or_mixed(crs_values)),
        "hydromodpy_skipped_observations": skipped,
        "features": features,
    }
    return write_geojson(path, collection)


def _features_from_watershed_vector(
    path: Path,
    *,
    catchment: DelineatedCatchment,
    selection_id: str,
    region_id: str,
    site_status: str,
) -> tuple[list[dict[str, Any]], str]:
    frame = read_watershed(path)
    if frame.empty:
        return [], _crs_label(frame.crs)
    properties = basin_properties(
        catchment,
        watershed_path=path,
        selection_id=selection_id,
        region_id=region_id,
        site_status=site_status,
    )
    features = []
    for index, geometry in enumerate(frame.geometry):
        geometry = repair_geometry_for_export(geometry)
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


def _crs_label(value: object) -> str:
    return "" if value is None else str(value)


__all__ = [
    "write_basins_geojson",
    "write_geojson",
    "write_observation_points_geojson",
    "write_outlets_geojson",
]
