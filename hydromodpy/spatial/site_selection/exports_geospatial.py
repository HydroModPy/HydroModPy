"""Production vector exports for site-selection spatial artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.spatial.site_selection.delineation import (
    DelineatedCatchment,
    outlet_display_xy,
    outlet_snap_distance_m,
    snapped_outlet_xy,
)
from hydromodpy.spatial.site_selection.schemas import site_record_from_catchment

GPKG_NAME = "site_selection.gpkg"


def write_selection_geopackage(
    path: str | Path,
    *,
    selected: Iterable[DelineatedCatchment],
    rejected: Iterable[DelineatedCatchment],
    selection_id: str,
    region_id: str = "",
) -> Path | None:
    """Write selected/rejected outlets and basins to one GeoPackage."""

    destination = Path(path)
    if destination.exists():
        destination.unlink()
    selected_list = list(selected)
    rejected_list = list(rejected)
    written = False
    for layer, frame in (
        (
            "selected_outlets",
            _outlets_gdf(
                selected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="selected",
            ),
        ),
        (
            "rejected_outlets",
            _outlets_gdf(
                rejected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="rejected",
            ),
        ),
        (
            "selected_basins",
            _basins_gdf(
                selected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="selected",
            ),
        ),
        (
            "rejected_basins",
            _basins_gdf(
                rejected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="rejected",
            ),
        ),
    ):
        if frame.empty:
            continue
        _write_gpkg_layer(frame, destination, layer=layer)
        written = True
    return destination if written else None


def write_selection_geoparquet_layers(
    output_root: str | Path,
    *,
    selected: Iterable[DelineatedCatchment],
    rejected: Iterable[DelineatedCatchment],
    selection_id: str,
    region_id: str = "",
) -> dict[str, Path]:
    """Write selected/rejected outlets and basins as separate GeoParquet files."""

    root = Path(output_root)
    selected_list = list(selected)
    rejected_list = list(rejected)
    layer_specs = {
        "selected_outlets_geoparquet": (
            "selected_outlets.parquet",
            _outlets_gdf(
                selected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="selected",
            ),
        ),
        "rejected_outlets_geoparquet": (
            "rejected_outlets.parquet",
            _outlets_gdf(
                rejected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="rejected",
            ),
        ),
        "selected_basins_geoparquet": (
            "selected_basins.parquet",
            _basins_gdf(
                selected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="selected",
            ),
        ),
        "rejected_basins_geoparquet": (
            "rejected_basins.parquet",
            _basins_gdf(
                rejected_list,
                selection_id=selection_id,
                region_id=region_id,
                site_status="rejected",
            ),
        ),
    }
    paths: dict[str, Path] = {}
    for key, (filename, frame) in layer_specs.items():
        if frame.empty:
            continue
        paths[key] = write_geoparquet_atomic(frame, root / filename)
    return paths


def write_observation_points_geopackage(
    path: str | Path,
    evidence: Iterable[object],
    *,
    layer: str = "observation_points",
) -> Path | None:
    """Append normalized observation points to a GeoPackage."""

    frame = observation_points_gdf(evidence)
    if frame.empty:
        return None
    destination = Path(path)
    _write_gpkg_layer(frame, destination, layer=layer)
    return destination


def write_observation_points_geoparquet(
    path: str | Path,
    evidence: Iterable[object],
) -> Path | None:
    """Write normalized observation points to GeoParquet."""

    frame = observation_points_gdf(evidence)
    if frame.empty:
        return None
    return write_geoparquet_atomic(frame, path)


def observation_points_gdf(evidence: Iterable[object]):
    """Return normalized observation evidence as a point GeoDataFrame."""

    import geopandas as gpd
    from shapely.geometry import Point

    rows = [
        item.to_record() if hasattr(item, "to_record") else dict(item)
        for item in evidence
    ]
    records: list[dict[str, Any]] = []
    geometries = []
    crs_values: list[str] = []
    for row in rows:
        location = _observation_location(row)
        if location is None:
            continue
        x, y, crs = location
        if crs:
            crs_values.append(crs)
        records.append(
            _clean_properties(
                {
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
            )
        )
        geometries.append(Point(x, y))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=_single_crs(crs_values))


def _outlets_gdf(
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str,
    site_status: str,
):
    import geopandas as gpd
    from shapely.geometry import Point

    materialized = list(catchments)
    records: list[dict[str, Any]] = []
    geometries = []
    crs_values: list[str] = []
    for catchment in materialized:
        display_x, display_y = outlet_display_xy(catchment)
        snapped = snapped_outlet_xy(catchment)
        snap_distance = outlet_snap_distance_m(catchment)
        if catchment.outlet.crs:
            crs_values.append(catchment.outlet.crs)
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
            "x_outlet_snapped": None if snapped is None else snapped[0],
            "y_outlet_snapped": None if snapped is None else snapped[1],
            "outlet_snap_distance_m": snap_distance,
            "catchment_status": catchment.status,
            "failure_reason": catchment.failure_reason,
            "watershed_shp": catchment.watershed_shp or "",
            "enabled": site_status == "selected",
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
        records.append(_clean_properties(properties))
        geometries.append(Point(display_x, display_y))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=_single_crs(crs_values))


def _basins_gdf(
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str,
    site_status: str,
):
    import geopandas as gpd
    import pandas as pd

    frames = []
    target_crs = ""
    for catchment in catchments:
        watershed_path = Path(catchment.watershed_shp or "")
        if not catchment.watershed_shp or not watershed_path.is_file():
            continue
        try:
            frame = gpd.read_file(str(watershed_path))
        except Exception:
            continue
        if frame.empty:
            continue
        frame = _repair_frame_geometries(frame)
        if frame.empty:
            continue
        if frame.crs is None and catchment.outlet.crs:
            frame = frame.set_crs(catchment.outlet.crs, allow_override=True)
        if not target_crs:
            target_crs = "" if frame.crs is None else str(frame.crs)
        elif frame.crs is not None and str(frame.crs) != target_crs:
            frame = frame.to_crs(target_crs)
        properties = _clean_properties(
            {
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
                "watershed_shp": str(watershed_path),
                "enabled": site_status == "selected",
            }
        )
        export_frame = gpd.GeoDataFrame(
            [properties for _geometry in frame.geometry],
            geometry=list(frame.geometry),
            crs=frame.crs,
        )
        frames.append(export_frame)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=None)
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=frames[0].crs,
    )


def _write_gpkg_layer(frame: object, destination: Path, *, layer: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(destination), layer=layer, driver="GPKG")


def _repair_frame_geometries(frame):
    frame = frame.copy()
    frame.geometry = [_repair_geometry_for_export(geometry) for geometry in frame.geometry]
    frame = frame[frame.geometry.notna()]
    if frame.empty:
        return frame
    return frame[~frame.geometry.is_empty]


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


def _single_crs(values: Iterable[str]) -> str | None:
    clean = [value for value in values if value]
    if not clean:
        return None
    return clean[0]


def _clean_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _clean_value(value) for key, value in properties.items()}


def _clean_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


__all__ = [
    "GPKG_NAME",
    "observation_points_gdf",
    "write_observation_points_geopackage",
    "write_observation_points_geoparquet",
    "write_selection_geopackage",
    "write_selection_geoparquet_layers",
]
