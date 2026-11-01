"""Geology and piezometer evidence computed from configured vector layers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from hydromodpy.core.io.crs import same_crs
from hydromodpy.site_selection.config.criteria_config import (
    GeologyCriteriaConfig,
)
from hydromodpy.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
)
from hydromodpy.site_selection.domain.export_values import clean_value
from hydromodpy.site_selection.domain.watershed import watershed_geometry


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

    layers = [load_vector_layer(layer) for layer in config.layers]
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
        annotated.append(copy_catchment_with_attributes(catchment, attributes))
        all_evidence.extend(site_evidence)
    return annotated, all_evidence


def _match_geology_layer_to_catchment(
    catchment: DelineatedCatchment,
    *,
    layer_cfg: object,
    layer_frame: object,
) -> list[GeologyEvidence]:
    if layer_frame.empty:
        return []
    target_crs = catchment.outlet.crs
    basin = watershed_geometry(catchment.watershed_shp, crs=target_crs)
    if basin is None:
        return []

    frame = frame_in_target_crs(layer_frame, target_crs=target_crs)
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
        geology_class = field_text(row, class_field)
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
        feature_id = field_text(row, getattr(layer_cfg, "id_field", None)) or str(index)
        feature_label = field_text(row, getattr(layer_cfg, "label_field", None))
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


def load_vector_layer(layer_cfg: object) -> tuple[object, object]:
    import geopandas as gpd

    path = Path(layer_cfg.path).expanduser().resolve()
    frame = gpd.read_file(path)
    return layer_cfg, frame


def frame_in_target_crs(frame: object, *, target_crs: str):
    if frame.crs is None:
        return frame.set_crs(target_crs, allow_override=True)
    if not same_crs(str(frame.crs), target_crs):
        return frame.to_crs(target_crs)
    return frame


def copy_catchment_with_attributes(
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


def representative_point(geometry: object):
    if geometry.geom_type == "Point":
        return geometry
    return geometry.representative_point()


def field_text(row: Mapping[str, Any], field_name: str | None) -> str:
    if not field_name:
        return ""
    value = row.get(field_name)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def field_float(row: Mapping[str, Any], field_name: str | None) -> float | None:
    text = field_text(row, field_name)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def feature_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in row.items():
        if key == "geometry":
            continue
        metadata[str(key)] = clean_value(value)
    return metadata


__all__ = [
    "GeologyEvidence",
    "annotate_catchments_with_geology_layers",
]
