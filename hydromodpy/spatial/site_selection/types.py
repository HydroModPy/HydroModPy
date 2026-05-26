"""Typed records produced by the site-selection workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hydromodpy.spatial.site_selection.station_influence import (
    station_influence_diagnostics,
)


@dataclass(frozen=True)
class ObservationSpatialMatch:
    """Spatial relationship between one observation feature and one candidate site."""

    distance_to_outlet_km: float | None = None
    distance_to_basin_km: float | None = None
    inside_basin: bool | None = None


@dataclass(frozen=True)
class ObservationEvidence:
    """Normalized audit record for one observation considered during selection.

    This is not a provider-specific schema. For a Hub'Eau station, provider
    metadata fills only part of the record. Spatial relationships and influence
    diagnostics are computed by the selection workflow or by independent data
    layers.
    """

    site_id: str
    observation_type: str
    source_dataset: str
    feature_id: str
    feature_label: str = ""
    distance_to_outlet_km: float | None = None
    distance_to_basin_km: float | None = None
    inside_basin: bool | None = None
    record_start: str | None = None
    record_end: str | None = None
    record_year_count: float | None = None
    quality_status: str = "unknown"
    influence_status: str = "unknown"
    influence_flags: list[str] = field(default_factory=list)
    upstream_dam_count: int | None = None
    upstream_major_withdrawal_count: int | None = None
    regulated_reach_flag: bool | None = None
    evidence_json: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_point_record(
        cls,
        *,
        site_id: str,
        observation_type: str,
        record: Any,
        spatial_match: ObservationSpatialMatch | None = None,
        influence_status: str = "unknown",
        influence_flags: list[str] | None = None,
        upstream_dam_count: int | None = None,
        upstream_major_withdrawal_count: int | None = None,
        regulated_reach_flag: bool | None = None,
        source_dataset: str | None = None,
    ) -> ObservationEvidence:
        """Build normalized evidence from a ``PointRecord``-like object."""

        location = getattr(record, "location", None)
        metadata = dict(getattr(location, "metadata", {}) or {})
        station_id = str(getattr(record, "station_id", "") or getattr(location, "id", ""))
        feature_label = str(
            metadata.get("station_name")
            or metadata.get("label")
            or metadata.get("name")
            or station_id
        )
        record_start, record_end = _record_data_bounds(record)
        quality_status = _quality_status(record)
        match = spatial_match or ObservationSpatialMatch()
        source = source_dataset or str(getattr(record, "source", "") or "unknown")
        influence = station_influence_diagnostics(metadata)
        resolved_influence_status = (
            influence.status if influence_status == "unknown" else influence_status
        )
        resolved_influence_flags = (
            list(influence.flags) if influence_flags is None else list(influence_flags)
        )

        evidence = {
            "provider_station_id": station_id,
            "variable": getattr(record, "variable", None),
            "unit": getattr(record, "unit", None),
            "source_unit": getattr(record, "source_unit", None),
            "frequency": getattr(record, "frequency", None),
            "n_records": int(getattr(record, "n_records", 0) or 0),
            "provider_metadata": _jsonable_mapping(metadata),
            "quality": _jsonable_mapping(getattr(record, "quality", None) or {}),
            "station_influence": {
                "status": influence.status,
                "flags": list(influence.flags),
                "matched_keywords": list(influence.matched_keywords),
                "raw_fields": _jsonable_mapping(influence.raw_fields),
            },
        }
        if location is not None:
            evidence["provider_location"] = {
                "x": getattr(location, "x", None),
                "y": getattr(location, "y", None),
                "crs": getattr(location, "crs", None),
            }

        return cls(
            site_id=site_id,
            observation_type=observation_type,
            source_dataset=source,
            feature_id=station_id,
            feature_label=feature_label,
            distance_to_outlet_km=match.distance_to_outlet_km,
            distance_to_basin_km=match.distance_to_basin_km,
            inside_basin=match.inside_basin,
            record_start=_date_to_iso(record_start),
            record_end=_date_to_iso(record_end),
            record_year_count=_record_year_count(record_start, record_end),
            quality_status=quality_status,
            influence_status=resolved_influence_status,
            influence_flags=resolved_influence_flags,
            upstream_dam_count=upstream_dam_count,
            upstream_major_withdrawal_count=upstream_major_withdrawal_count,
            regulated_reach_flag=regulated_reach_flag,
            evidence_json=evidence,
        )

    def to_record(self) -> dict[str, Any]:
        """Return a JSON/parquet-friendly mapping."""

        return {
            "site_id": self.site_id,
            "observation_type": self.observation_type,
            "source_dataset": self.source_dataset,
            "feature_id": self.feature_id,
            "feature_label": self.feature_label,
            "distance_to_outlet_km": self.distance_to_outlet_km,
            "distance_to_basin_km": self.distance_to_basin_km,
            "inside_basin": self.inside_basin,
            "record_start": self.record_start,
            "record_end": self.record_end,
            "record_year_count": self.record_year_count,
            "quality_status": self.quality_status,
            "influence_status": self.influence_status,
            "influence_flags": list(self.influence_flags),
            "upstream_dam_count": self.upstream_dam_count,
            "upstream_major_withdrawal_count": self.upstream_major_withdrawal_count,
            "regulated_reach_flag": self.regulated_reach_flag,
            "evidence_json": dict(self.evidence_json),
        }


def _record_data_bounds(record: Any) -> tuple[datetime | None, datetime | None]:
    data = getattr(record, "data", None)
    if data is not None and not getattr(data, "empty", True) and "datetime" in data:
        values = data["datetime"].dropna()
        if not values.empty:
            start = values.min().to_pydatetime()
            end = values.max().to_pydatetime()
            return start, end
    return getattr(record, "date_start", None), getattr(record, "date_end", None)


def _record_year_count(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if end < start:
        return None
    return round(((end - start).days + 1) / 365.25, 3)


def _date_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat()


def _quality_status(record: Any) -> str:
    if not bool(getattr(record, "has_data", False)):
        return "no_data"
    quality = getattr(record, "quality", None) or {}
    completeness = quality.get("completeness_pct")
    if completeness is None:
        return "unknown"
    value = float(completeness)
    if value >= 90.0:
        return "good"
    if value >= 50.0:
        return "partial"
    return "sparse"


def _jsonable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, (str, int, float, bool)) or item is None:
            out[str(key)] = item
        elif hasattr(item, "isoformat"):
            out[str(key)] = item.isoformat()
        else:
            out[str(key)] = str(item)
    return out


__all__ = ["ObservationEvidence", "ObservationSpatialMatch"]
