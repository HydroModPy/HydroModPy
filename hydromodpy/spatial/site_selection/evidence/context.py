"""Geology and piezometer evidence computed from configured vector layers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import (
    GeologyCriteriaConfig,
    ObservationsCriteriaConfig,
)
from hydromodpy.spatial.site_selection.domain.observations import ObservationEvidence
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
    outlet_display_xy,
)


@dataclass(frozen=True)
class GeologyEvidence:
    """One geology class intersecting one candidate basin."""

    site_id: str
    source_layer: str
    geology_class: str
    area_fraction: float
    area_km2: float
    feature_count: int
    source_path: str = ""
    feature_ids: list[str] = field(default_factory=list)
    feature_labels: list[str] = field(default_factory=list)
    geometry: Any = None
    crs: str = ""
    evidence_json: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a JSONL-friendly mapping without geometry payload."""

        return {
            "site_id": self.site_id,
            "source_layer": self.source_layer,
            "geology_class": self.geology_class,
            "area_fraction": self.area_fraction,
            "area_km2": self.area_km2,
            "feature_count": self.feature_count,
            "source_path": self.source_path,
            "feature_ids": list(self.feature_ids),
            "feature_labels": list(self.feature_labels),
            "crs": self.crs,
            "evidence_json": dict(self.evidence_json),
        }


def annotate_catchments_with_geology_layers(
    catchments: Iterable[DelineatedCatchment],
    *,
    config: GeologyCriteriaConfig,
) -> tuple[list[DelineatedCatchment], list[GeologyEvidence]]:
    """Compute dominant geology attributes from configured polygon layers."""

    materialized = list(catchments)
    if not config.layers:
        return materialized, []

    layers = [_load_vector_layer(layer) for layer in config.layers]
    annotated: list[DelineatedCatchment] = []
    all_evidence: list[GeologyEvidence] = []
    for catchment in materialized:
        attributes = dict(catchment.outlet.attributes)
        site_evidence: list[GeologyEvidence] = []
        for layer_cfg, layer_frame in layers:
            site_evidence.extend(
                _match_geology_layer_to_catchment(
                    catchment,
                    layer_cfg=layer_cfg,
                    layer_frame=layer_frame,
                )
            )
        _apply_geology_attributes(attributes, site_evidence)
        annotated.append(_copy_catchment_with_attributes(catchment, attributes))
        all_evidence.extend(site_evidence)
    return annotated, all_evidence


def annotate_catchments_with_piezometer_layers(
    catchments: Iterable[DelineatedCatchment],
    *,
    config: ObservationsCriteriaConfig,
) -> tuple[list[DelineatedCatchment], list[ObservationEvidence]]:
    """Compute piezometer attributes and normalized observation evidence."""

    materialized = list(catchments)
    if not config.piezometer_layers:
        return materialized, []

    layers = [_load_vector_layer(layer) for layer in config.piezometer_layers]
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
        annotated.append(_copy_catchment_with_attributes(catchment, attributes))
        all_evidence.extend(site_evidence)
    return annotated, all_evidence


def write_geology_evidence_geojson(
    path: str | Path,
    evidence: Iterable[GeologyEvidence],
) -> Path | None:
    """Write geology evidence as basin GeoJSON features."""

    materialized = [item for item in evidence if item.geometry is not None]
    if not materialized:
        return None
    crs_values = {item.crs for item in materialized if item.crs}
    features = [
        {
            "type": "Feature",
            "id": _geology_feature_id(item),
            "geometry": item.geometry.__geo_interface__,
            "properties": _properties_without_geometry(item),
        }
        for item in materialized
    ]
    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_geometry_role": "geology_basins",
        "hydromodpy_coordinate_crs": _single_or_mixed(crs_values),
        "features": features,
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(collection, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_geology_evidence_geopackage(
    path: str | Path,
    evidence: Iterable[GeologyEvidence],
    *,
    layer: str = "geology_basins",
) -> Path | None:
    """Write geology evidence to a GeoPackage layer."""

    frame = geology_evidence_gdf(evidence)
    if frame.empty:
        return None
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(destination), layer=layer, driver="GPKG")
    return destination


def write_geology_evidence_geoparquet(
    path: str | Path,
    evidence: Iterable[GeologyEvidence],
) -> Path | None:
    """Write geology evidence to GeoParquet."""

    frame = geology_evidence_gdf(evidence)
    if frame.empty:
        return None
    return write_geoparquet_atomic(frame, path)


def geology_evidence_gdf(evidence: Iterable[GeologyEvidence]):
    """Return geology evidence as a GeoDataFrame."""

    import geopandas as gpd

    materialized = [item for item in evidence if item.geometry is not None]
    crs = _single_crs(item.crs for item in materialized)
    records = [_properties_without_geometry(item) for item in materialized]
    geometries = [item.geometry for item in materialized]
    return gpd.GeoDataFrame(records, geometry=geometries, crs=crs)


def _match_geology_layer_to_catchment(
    catchment: DelineatedCatchment,
    *,
    layer_cfg: object,
    layer_frame: object,
) -> list[GeologyEvidence]:
    if layer_frame.empty:
        return []
    target_crs = catchment.outlet.crs
    basin = _basin_geometry(catchment, target_crs=target_crs)
    if basin is None:
        return []

    frame = _frame_in_target_crs(layer_frame, target_crs=target_crs)
    matches = frame[frame.geometry.intersects(basin)].copy()
    if matches.empty:
        return []

    class_field = str(layer_cfg.class_field)
    source_path = str(Path(layer_cfg.path).expanduser())
    class_areas: dict[str, dict[str, Any]] = {}
    for index, row in matches.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        geology_class = _field_text(row, class_field)
        if not geology_class:
            continue
        try:
            intersection = geometry.intersection(basin)
        except Exception:
            continue
        if intersection is None or intersection.is_empty:
            continue
        area_m2 = float(intersection.area)
        if area_m2 <= 0.0:
            continue
        entry = class_areas.setdefault(
            geology_class,
            {
                "area_m2": 0.0,
                "feature_count": 0,
                "feature_ids": [],
                "feature_labels": [],
            },
        )
        entry["area_m2"] += area_m2
        entry["feature_count"] += 1
        feature_id = _field_text(row, getattr(layer_cfg, "id_field", None)) or str(index)
        feature_label = _field_text(row, getattr(layer_cfg, "label_field", None))
        entry["feature_ids"].append(feature_id)
        entry["feature_labels"].append(feature_label or feature_id)

    basin_area_m2 = float(basin.area)
    if basin_area_m2 <= 0.0:
        return []
    coverage_fraction = sum(value["area_m2"] for value in class_areas.values()) / basin_area_m2
    return [
        GeologyEvidence(
            site_id=catchment.site_id,
            source_layer=str(layer_cfg.name),
            geology_class=geology_class,
            area_fraction=float(values["area_m2"]) / basin_area_m2,
            area_km2=float(values["area_m2"]) / 1_000_000.0,
            feature_count=int(values["feature_count"]),
            source_path=source_path,
            feature_ids=list(values["feature_ids"]),
            feature_labels=list(values["feature_labels"]),
            geometry=basin,
            crs=target_crs,
            evidence_json={
                "layer_path": source_path,
                "class_field": class_field,
                "coverage_fraction": coverage_fraction,
                "basin_area_km2": basin_area_m2 / 1_000_000.0,
            },
        )
        for geology_class, values in sorted(class_areas.items())
    ]


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
    frame = _frame_in_target_crs(layer_frame, target_crs=target_crs)
    outlet = Point(*outlet_display_xy(catchment))
    basin = _basin_geometry(catchment, target_crs=target_crs)
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
        point = _representative_point(geometry)
        feature_id = _field_text(row, getattr(layer_cfg, "id_field", None)) or str(index)
        feature_label = _field_text(row, getattr(layer_cfg, "label_field", None)) or feature_id
        record_years = _field_float(row, getattr(layer_cfg, "record_years_field", None))
        quality_status = _field_text(row, getattr(layer_cfg, "quality_field", None)) or "unknown"
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
                    "provider_metadata": _feature_metadata(row),
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


def _apply_geology_attributes(
    attributes: dict[str, Any],
    evidence: Iterable[GeologyEvidence],
) -> None:
    materialized = list(evidence)
    if not materialized:
        return
    dominant = max(materialized, key=lambda item: (item.area_fraction, item.area_km2))
    fractions = {
        item.geology_class: item.area_fraction
        for item in sorted(materialized, key=lambda item: item.geology_class)
    }
    attributes["geology_class"] = dominant.geology_class
    attributes["dominant_geology"] = dominant.geology_class
    attributes["geology_source"] = dominant.source_layer
    attributes["geology_area_fraction"] = dominant.area_fraction
    attributes["geology_diversity_count"] = len({item.geology_class for item in materialized})
    attributes["geology_fractions_json"] = json.dumps(
        fractions,
        ensure_ascii=True,
        sort_keys=True,
    )


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


def _load_vector_layer(layer_cfg: object) -> tuple[object, object]:
    import geopandas as gpd

    path = Path(layer_cfg.path).expanduser().resolve()
    frame = gpd.read_file(path)
    return layer_cfg, frame


def _basin_geometry(catchment: DelineatedCatchment, *, target_crs: str):
    import geopandas as gpd

    path = Path(catchment.watershed_shp or "")
    if not catchment.watershed_shp or not path.is_file():
        return None
    frame = gpd.read_file(path)
    if frame.empty:
        return None
    frame = _frame_in_target_crs(frame, target_crs=target_crs)
    geometries = [
        geometry for geometry in frame.geometry if geometry is not None and not geometry.is_empty
    ]
    if not geometries:
        return None
    union = (
        frame.geometry.union_all() if hasattr(frame.geometry, "union_all") else frame.unary_union
    )
    return None if union is None or union.is_empty else union


def _frame_in_target_crs(frame: object, *, target_crs: str):
    if frame.crs is None:
        return frame.set_crs(target_crs, allow_override=True)
    if not _same_crs(str(frame.crs), target_crs):
        return frame.to_crs(target_crs)
    return frame


def _copy_catchment_with_attributes(
    catchment: DelineatedCatchment,
    attributes: dict[str, Any],
) -> DelineatedCatchment:
    return replace(
        catchment,
        outlet=CandidateOutlet(
            candidate_id=catchment.outlet.candidate_id,
            x=catchment.outlet.x,
            y=catchment.outlet.y,
            crs=catchment.outlet.crs,
            source=catchment.outlet.source,
            source_feature_id=catchment.outlet.source_feature_id,
            source_label=catchment.outlet.source_label,
            priority=catchment.outlet.priority,
            attributes=attributes,
        ),
    )


def _representative_point(geometry: object):
    if geometry.geom_type == "Point":
        return geometry
    return geometry.representative_point()


def _field_text(row: Mapping[str, Any], field_name: str | None) -> str:
    if not field_name:
        return ""
    value = row.get(field_name)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _field_float(row: Mapping[str, Any], field_name: str | None) -> float | None:
    text = _field_text(row, field_name)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _feature_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in row.items():
        if key == "geometry":
            continue
        metadata[str(key)] = _clean_value(value)
    return metadata


def _properties_without_geometry(item: GeologyEvidence) -> dict[str, Any]:
    record = item.to_record()
    return {key: _clean_value(value) for key, value in record.items() if key != "evidence_json"} | {
        "evidence_json": json.dumps(item.evidence_json, ensure_ascii=True, sort_keys=True)
    }


def _geology_feature_id(item: GeologyEvidence) -> str:
    return f"{item.site_id}:{item.source_layer}:{item.geology_class}"


def _same_crs(left: str, right: str) -> bool:
    if left.strip().upper() == right.strip().upper():
        return True
    try:
        from pyproj import CRS

        return CRS.from_user_input(left) == CRS.from_user_input(right)
    except Exception:
        return False


def _single_crs(values: Iterable[str]) -> str | None:
    clean = [value for value in values if value]
    if not clean:
        return None
    return clean[0]


def _single_or_mixed(values: set[str]) -> str:
    clean = {value for value in values if value}
    if not clean:
        return ""
    if len(clean) == 1:
        return next(iter(clean))
    return "mixed"


def _clean_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


__all__ = [
    "GeologyEvidence",
    "annotate_catchments_with_geology_layers",
    "annotate_catchments_with_piezometer_layers",
    "geology_evidence_gdf",
    "write_geology_evidence_geojson",
    "write_geology_evidence_geopackage",
    "write_geology_evidence_geoparquet",
]
