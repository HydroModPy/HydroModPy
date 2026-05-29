"""Automatic anthropic-influence evidence for site selection."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import InfluenceCriteriaConfig
from hydromodpy.spatial.site_selection.evidence.refs import influence_evidence_ref
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
    outlet_display_xy,
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

    layers = [_load_influence_layer(layer) for layer in config.layers]
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
        annotated.append(
            replace(
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
        )
        all_evidence.extend(site_evidence)
    return annotated, all_evidence


def write_influence_evidence_geojson(
    path: str | Path,
    evidence: Iterable[InfluenceEvidence],
) -> Path | None:
    """Write matched influence features as GeoJSON."""

    materialized = [item for item in evidence if item.geometry is not None]
    if not materialized:
        return None
    crs_values = {item.crs for item in materialized if item.crs}
    features = [
        {
            "type": "Feature",
            "id": _evidence_feature_id(item),
            "geometry": item.geometry.__geo_interface__,
            "properties": _properties_without_geometry(item),
        }
        for item in materialized
    ]
    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_geometry_role": "influence_features",
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


def write_influence_evidence_geopackage(
    path: str | Path,
    evidence: Iterable[InfluenceEvidence],
    *,
    layer: str = "influence_features",
) -> Path | None:
    """Write matched influence features to a GeoPackage layer."""

    frame = influence_evidence_gdf(evidence)
    if frame.empty:
        return None
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(destination), layer=layer, driver="GPKG")
    return destination


def write_influence_evidence_geoparquet(
    path: str | Path,
    evidence: Iterable[InfluenceEvidence],
) -> Path | None:
    """Write matched influence features to GeoParquet."""

    frame = influence_evidence_gdf(evidence)
    if frame.empty:
        return None
    return write_geoparquet_atomic(frame, path)


def influence_evidence_gdf(evidence: Iterable[InfluenceEvidence]):
    """Return influence evidence as a GeoDataFrame."""

    import geopandas as gpd

    materialized = [item for item in evidence if item.geometry is not None]
    crs = _single_crs(item.crs for item in materialized)
    records = [_properties_without_geometry(item) for item in materialized]
    geometries = [item.geometry for item in materialized]
    return gpd.GeoDataFrame(records, geometry=geometries, crs=crs)


def _load_influence_layer(layer_cfg: object) -> tuple[object, object]:
    import geopandas as gpd

    path = Path(layer_cfg.path).expanduser().resolve()
    frame = gpd.read_file(path)
    return layer_cfg, frame


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
    frame = layer_frame
    if frame.crs is None:
        frame = frame.set_crs(target_crs, allow_override=True)
    elif not _same_crs(str(frame.crs), target_crs):
        frame = frame.to_crs(target_crs)

    basin = _basin_geometry(catchment, target_crs=target_crs)
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
        severity = _field_text(row, getattr(layer_cfg, "severity_field", None))
        feature_id = _field_text(row, getattr(layer_cfg, "id_field", None)) or str(index)
        feature_label = _field_text(row, getattr(layer_cfg, "label_field", None)) or feature_id
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


def _basin_geometry(catchment: DelineatedCatchment, *, target_crs: str):
    import geopandas as gpd

    path = Path(catchment.watershed_shp or "")
    if not catchment.watershed_shp or not path.is_file():
        return None
    frame = gpd.read_file(path)
    if frame.empty:
        return None
    if frame.crs is None:
        frame = frame.set_crs(target_crs, allow_override=True)
    elif not _same_crs(str(frame.crs), target_crs):
        frame = frame.to_crs(target_crs)
    geometries = [geometry for geometry in frame.geometry if geometry is not None and not geometry.is_empty]
    if not geometries:
        return None
    union = frame.geometry.union_all() if hasattr(frame.geometry, "union_all") else frame.unary_union
    return None if union is None or union.is_empty else union


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
    major_values = [str(value).strip().lower() for value in getattr(layer_cfg, "major_values", []) or []]
    severity_field = getattr(layer_cfg, "severity_field", None)
    if not severity_field or not major_values:
        return True
    return str(row.get(severity_field, "")).strip().lower() in set(major_values)


def _field_text(row: Mapping[str, Any], field_name: str | None) -> str:
    if not field_name:
        return ""
    value = row.get(field_name)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _properties_without_geometry(item: InfluenceEvidence) -> dict[str, Any]:
    record = item.to_record()
    return {key: _clean_value(value) for key, value in record.items() if key != "evidence_json"} | {
        "evidence_json": json.dumps(item.evidence_json, ensure_ascii=True, sort_keys=True)
    }


def _evidence_feature_id(item: InfluenceEvidence) -> str:
    return f"{item.site_id}:{item.influence_type}:{item.feature_id or item.feature_index}"


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
    "InfluenceEvidence",
    "annotate_catchments_with_influence_layers",
    "influence_evidence_gdf",
    "write_influence_evidence_geojson",
    "write_influence_evidence_geopackage",
    "write_influence_evidence_geoparquet",
]
