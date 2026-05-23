"""Observation normalization helpers for site selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hydromodpy.spatial.site_selection.types import (
    ObservationEvidence,
    ObservationSpatialMatch,
)


def build_observation_evidence(
    *,
    site_id: str,
    observation_type: str,
    records: Iterable[Any],
    spatial_matches: Mapping[str, ObservationSpatialMatch] | None = None,
    source_dataset: str | None = None,
) -> list[ObservationEvidence]:
    """Convert provider records into normalized observation evidence.

    Parameters
    ----------
    site_id:
        Candidate or selected site identifier.
    observation_type:
        Normalized observation family, for example ``flow_station`` or
        ``piezometer``.
    records:
        PointRecord-like objects returned by data providers.
    spatial_matches:
        Optional map from station id to spatial relationship with the site.
        These values are computed by site selection, not by Hub'Eau.
    source_dataset:
        Optional override for the provider/source label written in the evidence.
    """

    matches = spatial_matches or {}
    evidence: list[ObservationEvidence] = []
    for record in records:
        station_id = str(getattr(record, "station_id", ""))
        evidence.append(
            ObservationEvidence.from_point_record(
                site_id=site_id,
                observation_type=observation_type,
                record=record,
                spatial_match=matches.get(station_id),
                source_dataset=source_dataset,
            )
        )
    return evidence


def build_observation_evidence_from_attributes(
    *,
    site_id: str,
    attributes: Mapping[str, Any],
) -> list[ObservationEvidence]:
    """Build normalized evidence from imported candidate/catchment attributes.

    This is for pre-normalized fixture or catalog inputs. Provider API access
    must still go through the existing data managers and ``PointRecord`` path.
    """

    evidence: list[ObservationEvidence] = []
    flow = _evidence_from_prefixed_attributes(
        site_id=site_id,
        observation_type="flow_station",
        default_source="imported_hydrometry",
        attributes=attributes,
        prefixes=("flow_station", "hydro_station", "station"),
    )
    if flow is not None:
        evidence.append(flow)
    piezometer = _evidence_from_prefixed_attributes(
        site_id=site_id,
        observation_type="piezometer",
        default_source="imported_piezometry",
        attributes=attributes,
        prefixes=("piezometer",),
    )
    if piezometer is not None:
        evidence.append(piezometer)
    return evidence


def _evidence_from_prefixed_attributes(
    *,
    site_id: str,
    observation_type: str,
    default_source: str,
    attributes: Mapping[str, Any],
    prefixes: tuple[str, ...],
) -> ObservationEvidence | None:
    feature_id = _first_text(attributes, *(f"{prefix}_id" for prefix in prefixes))
    if not feature_id:
        return None
    label = _first_text(attributes, *(f"{prefix}_label" for prefix in prefixes)) or feature_id
    source = _first_text(attributes, *(f"{prefix}_source" for prefix in prefixes)) or default_source
    x = _first_number(attributes, *(f"{prefix}_x" for prefix in prefixes))
    y = _first_number(attributes, *(f"{prefix}_y" for prefix in prefixes))
    crs = _first_text(attributes, *(f"{prefix}_crs" for prefix in prefixes))
    record_years = _first_number(
        attributes,
        *(f"{prefix}_record_years" for prefix in prefixes),
        *(f"{prefix}_record_year_count" for prefix in prefixes),
    )
    distance_to_outlet = _first_number(
        attributes,
        *(f"{prefix}_distance_km" for prefix in prefixes),
        *(f"{prefix}_to_outlet_distance_km" for prefix in prefixes),
        "station_to_outlet_distance_km",
    )
    distance_to_basin = _first_number(
        attributes,
        *(f"{prefix}_distance_to_basin_km" for prefix in prefixes),
    )
    inside_basin = _first_bool(
        attributes,
        *(f"{prefix}_inside_basin" for prefix in prefixes),
        "station_inside_basin",
        "station_inside_or_at_outlet",
    )
    evidence_json: dict[str, Any] = {
        "provider_station_id": feature_id,
        "provider_metadata": _prefixed_metadata(attributes, prefixes=prefixes),
    }
    if x is not None and y is not None:
        evidence_json["provider_location"] = {"x": x, "y": y, "crs": crs or ""}

    return ObservationEvidence(
        site_id=site_id,
        observation_type=observation_type,
        source_dataset=source,
        feature_id=feature_id,
        feature_label=label,
        distance_to_outlet_km=distance_to_outlet,
        distance_to_basin_km=distance_to_basin,
        inside_basin=inside_basin,
        record_year_count=record_years,
        quality_status=_first_text(attributes, *(f"{prefix}_quality_status" for prefix in prefixes))
        or "unknown",
        influence_status=_first_text(
            attributes,
            *(f"{prefix}_influence_status" for prefix in prefixes),
        )
        or "unknown",
        evidence_json=evidence_json,
    )


def _prefixed_metadata(
    attributes: Mapping[str, Any],
    *,
    prefixes: tuple[str, ...],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in attributes.items():
        text_key = str(key)
        if any(text_key.startswith(f"{prefix}_") for prefix in prefixes):
            metadata[text_key] = value
    return metadata


def _first_text(attributes: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_number(attributes: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = attributes.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_bool(attributes: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = attributes.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "t", "yes", "y", "oui", "o"}:
            return True
        if text in {"0", "false", "f", "no", "n", "non"}:
            return False
    return None


__all__ = [
    "build_observation_evidence",
    "build_observation_evidence_from_attributes",
]
