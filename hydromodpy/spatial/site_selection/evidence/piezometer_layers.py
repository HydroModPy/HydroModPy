"""Piezometer evidence of each catchment, read from the piezometer layers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.config.criteria_config import ObservationsCriteriaConfig
from hydromodpy.spatial.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_display_xy,
)
from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.spatial.site_selection.domain.watershed import watershed_geometry
from hydromodpy.spatial.site_selection.evidence.geology_layers import (
    copy_catchment_with_attributes,
    feature_metadata,
    field_float,
    field_text,
    frame_in_target_crs,
    load_vector_layer,
    representative_point,
)

__all__ = [
    "annotate_catchments_with_piezometer_layers",
]


def annotate_catchments_with_piezometer_layers(
    catchments: Iterable[DelineatedCatchment],
    *,
    config: ObservationsCriteriaConfig,
) -> tuple[list[DelineatedCatchment], list[ObservationEvidence]]:
    """Compute piezometer attributes and normalized observation evidence."""

    materialized = list(catchments)
    if not config.piezometer_layers:
        return materialized, []

    layers = [load_vector_layer(layer) for layer in config.piezometer_layers]
    annotated: list[DelineatedCatchment] = []
    all_evidence: list[ObservationEvidence] = []
    for catchment in materialized:
        attributes = dict(catchment.outlet.attributes)
        site_evidence: list[ObservationEvidence] = []
        for layer_cfg, layer_frame in layers:
            site_evidence.extend(
                _match_piezometer_layer_to_catchment(
                    catchment,
                    layer_cfg=layer_cfg,
                    layer_frame=layer_frame,
                    max_distance_km=config.piezometer_max_distance_km,
                )
            )
        _apply_piezometer_attributes(attributes, site_evidence)
        annotated.append(copy_catchment_with_attributes(catchment, attributes))
        all_evidence.extend(site_evidence)
    return annotated, all_evidence


def _match_piezometer_layer_to_catchment(
    catchment: DelineatedCatchment,
    *,
    layer_cfg: object,
    layer_frame: object,
    max_distance_km: float | None,
) -> list[ObservationEvidence]:
    from shapely.geometry import Point

    if layer_frame.empty:
        return []
    target_crs = catchment.outlet.crs
    frame = frame_in_target_crs(layer_frame, target_crs=target_crs)
    outlet = Point(*outlet_display_xy(catchment))
    basin = watershed_geometry(catchment.watershed_shp, crs=target_crs)
    radius_m = None if max_distance_km is None else float(max_distance_km) * 1000.0
    if basin is None and radius_m is None:
        return []

    matches = []
    for index, row in frame.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        inside_basin = bool(basin is not None and geometry.intersects(basin))
        distance_to_outlet_m = float(geometry.distance(outlet))
        if inside_basin or (radius_m is not None and distance_to_outlet_m <= radius_m):
            matches.append((index, row, inside_basin, distance_to_outlet_m))

    source_path = str(Path(layer_cfg.path).expanduser())
    evidence: list[ObservationEvidence] = []
    for index, row, inside_basin, distance_to_outlet_m in matches:
        geometry = row.geometry
        basin_distance_km = None
        if basin is not None:
            basin_distance_km = 0.0 if inside_basin else float(geometry.distance(basin) / 1000.0)
        point = representative_point(geometry)
        feature_id = field_text(row, getattr(layer_cfg, "id_field", None)) or str(index)
        feature_label = field_text(row, getattr(layer_cfg, "label_field", None)) or feature_id
        record_years = field_float(row, getattr(layer_cfg, "record_years_field", None))
        quality_status = field_text(row, getattr(layer_cfg, "quality_field", None)) or "unknown"
        evidence.append(
            ObservationEvidence(
                site_id=catchment.site_id,
                observation_type="piezometer",
                source_dataset=str(layer_cfg.name),
                feature_id=feature_id,
                feature_label=feature_label,
                distance_to_outlet_km=distance_to_outlet_m / 1000.0,
                distance_to_basin_km=basin_distance_km,
                inside_basin=inside_basin,
                record_year_count=record_years,
                quality_status=quality_status,
                evidence_json={
                    "provider_station_id": feature_id,
                    "provider_metadata": feature_metadata(row),
                    "provider_location": {
                        "x": float(point.x),
                        "y": float(point.y),
                        "crs": target_crs,
                    },
                    "layer_path": source_path,
                    "geometry_type": geometry.geom_type,
                },
            )
        )
    return evidence


def _apply_piezometer_attributes(
    attributes: dict[str, Any],
    evidence: Iterable[ObservationEvidence],
) -> None:
    materialized = list(evidence)
    if not materialized:
        return
    distances = [
        float(item.distance_to_outlet_km)
        for item in materialized
        if item.distance_to_outlet_km is not None
    ]
    inside_count = sum(1 for item in materialized if item.inside_basin is True)
    attributes["piezometer_count"] = len(materialized)
    attributes["nearby_piezometer_count"] = len(materialized)
    attributes["piezometers_in_basin"] = inside_count
    attributes["piezometer_inside_basin"] = inside_count > 0
    attributes["has_piezometer_inside_basin"] = inside_count > 0
    if distances:
        nearest = min(distances)
        nearest_item = min(
            materialized,
            key=lambda item: (
                float("inf")
                if item.distance_to_outlet_km is None
                else float(item.distance_to_outlet_km)
            ),
        )
        attributes["nearest_piezometer_distance_km"] = nearest
        attributes["piezometer_distance_km"] = nearest
        attributes["piezometer_to_outlet_distance_km"] = nearest
        attributes["piezometer_id"] = nearest_item.feature_id
        attributes["piezometer_label"] = nearest_item.feature_label
        attributes["piezometer_source"] = nearest_item.source_dataset
