"""Candidate outlet records and lightweight thinning helpers."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pyproj import Transformer

from hydromodpy.core.io.crs import haversine_km, same_crs
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.station_influence import STATION_INFLUENCE_FIELDS


def candidate_outlets_from_point_records(
    records: Iterable[Any],
    *,
    candidate_prefix: str = "obs",
    source: str = "observation",
    default_crs: str | None = None,
    target_crs: str | None = None,
) -> list[CandidateOutlet]:
    """Build candidate outlets from PointRecord-like observations.

    Records without a location are skipped. When ``target_crs`` is provided,
    coordinates are converted before the candidate is emitted. Hub'Eau station
    metadata often contains Lambert-93 coordinates alongside WGS84 longitude and
    latitude; those provider coordinates are used directly when Lambert-93 is the
    requested target CRS.
    """

    candidates: list[CandidateOutlet] = []
    for record in records:
        location = getattr(record, "location", None)
        if location is None:
            continue
        crs = str(getattr(location, "crs", "") or default_crs or "")
        if not crs:
            continue
        station_id = str(getattr(record, "station_id", "") or getattr(location, "id", ""))
        metadata = dict(getattr(location, "metadata", {}) or {})
        x, y, outlet_crs = _location_coordinates_for_target(
            x=float(location.x),
            y=float(location.y),
            source_crs=crs,
            target_crs=target_crs,
            metadata=metadata,
        )
        label = str(metadata.get("station_name") or metadata.get("name") or station_id)
        attributes = {
            "variable": getattr(record, "variable", None),
            "unit": getattr(record, "unit", None),
            "frequency": getattr(record, "frequency", None),
            "n_records": int(getattr(record, "n_records", 0) or 0),
            "provider_source": getattr(record, "source", None),
            "source_location_crs": crs,
            "flow_station_id": station_id,
            "flow_station_label": label,
            "flow_station_x": x,
            "flow_station_y": y,
            "flow_station_crs": outlet_crs,
        }
        attributes.update(_station_influence_attributes(metadata))
        candidates.append(
            CandidateOutlet(
                candidate_id=_make_candidate_id(candidate_prefix, station_id),
                x=x,
                y=y,
                crs=outlet_crs,
                source=source,
                source_feature_id=station_id,
                source_label=label,
                priority=float(attributes["n_records"] or 0),
                attributes=attributes,
            )
        )
    return candidates


def _station_influence_attributes(metadata: Mapping[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for field_name in STATION_INFLUENCE_FIELDS:
        value = metadata.get(field_name)
        if value in (None, ""):
            continue
        attributes[field_name] = value
        attributes[f"flow_station_{field_name}"] = value
    return attributes


def _location_coordinates_for_target(
    *,
    x: float,
    y: float,
    source_crs: str,
    target_crs: str | None,
    metadata: Mapping[str, Any],
) -> tuple[float, float, str]:
    """Return coordinates in the requested target CRS when needed."""

    if not target_crs or same_crs(source_crs, target_crs):
        return x, y, source_crs

    if _is_lambert93(target_crs):
        x_l93 = _float_or_none(metadata.get("x_l93"))
        y_l93 = _float_or_none(metadata.get("y_l93"))
        if x_l93 is not None and y_l93 is not None:
            return x_l93, y_l93, "EPSG:2154"

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    target_x, target_y = transformer.transform(x, y)
    return float(target_x), float(target_y), target_crs


def thin_candidate_outlets(
    candidates: Iterable[CandidateOutlet],
    *,
    min_distance_km: float,
) -> list[CandidateOutlet]:
    """Greedily keep high-priority candidates separated by a minimum distance."""

    if min_distance_km <= 0.0:
        raise ValueError("min_distance_km must be > 0.")

    ordered = sorted(
        candidates,
        key=lambda candidate: (-candidate.priority, candidate.candidate_id),
    )
    selected: list[CandidateOutlet] = []
    for candidate in ordered:
        if all(_distance_km(candidate, other) >= min_distance_km for other in selected):
            selected.append(candidate)
    return sorted(selected, key=lambda candidate: candidate.candidate_id)


def _make_candidate_id(prefix: str, raw_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", raw_id.strip())
    token = token.strip("_") or "candidate"
    return f"{prefix}_{token}"


def _distance_km(left: CandidateOutlet, right: CandidateOutlet) -> float:
    if _is_wgs84(left.crs) and _is_wgs84(right.crs):
        return haversine_km(left.x, left.y, right.x, right.y)
    if left.crs != right.crs:
        raise ValueError(
            "Cannot thin candidates with different projected CRS without prior reprojection: "
            f"{left.crs!r} != {right.crs!r}."
        )
    return math.hypot(left.x - right.x, left.y - right.y) / 1000.0


def _is_lambert93(crs: str) -> bool:
    token = str(crs).strip().upper().replace(" ", "")
    return token in {"EPSG:2154", "2154", "RGF93/LAMBERT-93"}


def _is_wgs84(crs: str) -> bool:
    token = str(crs).strip().upper()
    return token in {"EPSG:4326", "WGS84", "WGS 84"}


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


__all__ = [
    "candidate_outlets_from_point_records",
    "thin_candidate_outlets",
]
