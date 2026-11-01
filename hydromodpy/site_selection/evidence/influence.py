"""Automatic anthropic-influence evidence for site selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.site_selection.config.criteria_config import InfluenceCriteriaConfig
from hydromodpy.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_display_xy,
)
from hydromodpy.site_selection.domain.refs import influence_evidence_ref
from hydromodpy.site_selection.domain.watershed import watershed_geometry
from hydromodpy.site_selection.evidence.geology_layers import (
    copy_catchment_with_attributes,
    field_text,
    frame_in_target_crs,
    load_vector_layer,
)

INFLUENCE_FLAG_TO_COUNT = {
    "major_dam_upstream": "upstream_dam_count",
    "major_withdrawal_upstream": "upstream_major_withdrawal_count",
    "major_regulated_reach": "regulated_reach_count",
}


@dataclass(frozen=True)
class InfluenceEvidence:
    """One source feature matched against one candidate basin."""

    site_id: str
    influence_type: str
    source_layer: str
    feature_id: str = ""
    feature_label: str = ""
    severity: str = ""
    major: bool = True
    relation: str = "intersects_basin"
    distance_to_outlet_km: float | None = None
    inside_basin: bool | None = None
    source_path: str = ""
    feature_index: int | None = None
    geometry: Any = None
    crs: str = ""
    evidence_json: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a JSONL-friendly mapping without geometry payload."""

        return {
            "site_id": self.site_id,
            "influence_type": self.influence_type,
            "source_layer": self.source_layer,
            "feature_id": self.feature_id,
            "feature_label": self.feature_label,
            "severity": self.severity,
            "major": self.major,
            "relation": self.relation,
            "distance_to_outlet_km": self.distance_to_outlet_km,
            "inside_basin": self.inside_basin,
            "source_path": self.source_path,
            "feature_index": self.feature_index,
            "crs": self.crs,
            "evidence_json": dict(self.evidence_json),
        }


def annotate_catchments_with_influence_layers(
    catchments: Iterable[DelineatedCatchment],
    *,
    config: InfluenceCriteriaConfig,
) -> tuple[list[DelineatedCatchment], list[InfluenceEvidence]]:
    """Compute influence flags from configured vector layers."""

    materialized = list(catchments)
    if not config.layers:
        return materialized, []

    layers = [load_vector_layer(layer) for layer in config.layers]
    annotated: list[DelineatedCatchment] = []
    all_evidence: list[InfluenceEvidence] = []
    for catchment in materialized:
        site_evidence: list[InfluenceEvidence] = []
        attributes = dict(catchment.outlet.attributes)
        for layer_cfg, layer_frame in layers:
            evidence = _match_layer_to_catchment(
                catchment,
                layer_cfg=layer_cfg,
                layer_frame=layer_frame,
                search_radius_km=config.influence_search_radius_km,
            )
            site_evidence.extend(evidence)
        _apply_influence_flags(attributes, site_evidence)
        annotated.append(copy_catchment_with_attributes(catchment, attributes))
        all_evidence.extend(site_evidence)
    return annotated, all_evidence


def _match_layer_to_catchment(
    catchment: DelineatedCatchment,
    *,
    layer_cfg: object,
    layer_frame: object,
    search_radius_km: float | None,
) -> list[InfluenceEvidence]:
    from shapely.geometry import Point

    if layer_frame.empty:
        return []
    target_crs = catchment.outlet.crs
    frame = frame_in_target_crs(layer_frame, target_crs=target_crs)

    basin = watershed_geometry(catchment.watershed_shp, crs=target_crs)
    outlet = Point(*outlet_display_xy(catchment))
    relation = "intersects_basin"
    if basin is None:
        if search_radius_km is None:
            return []
        basin = outlet.buffer(float(search_radius_km) * 1000.0)
        relation = "within_outlet_search_radius"

    matches = frame[frame.geometry.intersects(basin)].copy()
    if matches.empty:
        return []
    source_path = str(Path(layer_cfg.path).expanduser())
    crs_label = target_crs
    evidence: list[InfluenceEvidence] = []
    for index, row in matches.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        major = _is_major_feature(row, layer_cfg=layer_cfg)
        severity = field_text(row, getattr(layer_cfg, "severity_field", None))
        feature_id = field_text(row, getattr(layer_cfg, "id_field", None)) or str(index)
        feature_label = field_text(row, getattr(layer_cfg, "label_field", None)) or feature_id
        distance_km = float(geometry.distance(outlet) / 1000.0)
        evidence.append(
            InfluenceEvidence(
                site_id=catchment.site_id,
                influence_type=str(layer_cfg.influence_type),
                source_layer=str(layer_cfg.name),
                feature_id=feature_id,
                feature_label=feature_label,
                severity=severity,
                major=major,
                relation=relation,
                distance_to_outlet_km=distance_km,
                inside_basin=bool(geometry.intersects(basin)),
                source_path=source_path,
                feature_index=int(index) if isinstance(index, int) else None,
                geometry=geometry,
                crs=crs_label,
                evidence_json={
                    "layer_path": source_path,
                    "geometry_type": geometry.geom_type,
                    "major_values": list(getattr(layer_cfg, "major_values", []) or []),
                },
            )
        )
    return evidence


def _apply_influence_flags(
    attributes: dict[str, Any],
    evidence: Iterable[InfluenceEvidence],
) -> None:
    materialized = list(evidence)
    major_counts: dict[str, int] = {key: 0 for key in INFLUENCE_FLAG_TO_COUNT}
    total_counts: dict[str, int] = {key: 0 for key in INFLUENCE_FLAG_TO_COUNT}
    refs_by_type: dict[str, list[str]] = {key: [] for key in INFLUENCE_FLAG_TO_COUNT}
    all_refs: list[str] = []
    for item in materialized:
        if item.influence_type not in major_counts:
            continue
        evidence_ref = influence_evidence_ref(
            site_id=item.site_id,
            influence_type=item.influence_type,
            feature_id=item.feature_id,
            feature_index=item.feature_index,
        )
        all_refs.append(evidence_ref)
        refs_by_type[item.influence_type].append(evidence_ref)
        total_counts[item.influence_type] += 1
        if item.major:
            major_counts[item.influence_type] += 1
    for flag, count_field in INFLUENCE_FLAG_TO_COUNT.items():
        if total_counts[flag] == 0:
            continue
        attributes[flag] = major_counts[flag] > 0
        attributes[count_field] = major_counts[flag]
        attributes[f"{flag}_feature_count"] = total_counts[flag]
        attributes[f"{flag}_evidence_refs"] = refs_by_type[flag]
    if any(total_counts.values()):
        attributes["influence_status"] = "known"
        attributes["influence_source"] = "vector_layers"
        attributes["influence_evidence_refs"] = all_refs


def _is_major_feature(row: Mapping[str, Any], *, layer_cfg: object) -> bool:
    major_values = [
        str(value).strip().lower() for value in getattr(layer_cfg, "major_values", []) or []
    ]
    severity_field = getattr(layer_cfg, "severity_field", None)
    if not severity_field or not major_values:
        return True
    return str(row.get(severity_field, "")).strip().lower() in set(major_values)


__all__ = [
    "InfluenceEvidence",
    "annotate_catchments_with_influence_layers",
]
