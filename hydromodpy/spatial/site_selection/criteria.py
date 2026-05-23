"""Criterion evaluation primitives for site selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    AreaRangeConfig,
    GeologyCriteriaConfig,
    InfluenceCriteriaConfig,
    ObservationsCriteriaConfig,
)


@dataclass(frozen=True)
class CriteriaComponent:
    """One auditable criterion contribution for one candidate site."""

    site_id: str
    selection_principle: str
    criterion_id: str
    criterion_family: str
    criterion_mode: str
    evaluation_stage: str
    evaluation_order: int
    criterion_status: str
    raw_value: float | str | bool | None = None
    normalized_value: float | None = None
    threshold: float | str | None = None
    weight: float | None = None
    score_component: float | None = None
    blocking: bool = False
    reason: str = ""
    evidence_json: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a CSV/parquet-friendly mapping."""

        return {
            "site_id": self.site_id,
            "selection_principle": self.selection_principle,
            "criterion_id": self.criterion_id,
            "criterion_family": self.criterion_family,
            "criterion_mode": self.criterion_mode,
            "evaluation_stage": self.evaluation_stage,
            "evaluation_order": self.evaluation_order,
            "criterion_status": self.criterion_status,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "threshold": self.threshold,
            "weight": self.weight,
            "score_component": self.score_component,
            "blocking": self.blocking,
            "reason": self.reason,
            "evidence_json": dict(self.evidence_json),
        }


def evaluate_area_criterion(
    *,
    site_id: str,
    area_km2: float | None,
    config: AreaCriteriaConfig,
    selection_principle: str,
    evaluation_order: int = 0,
) -> CriteriaComponent:
    """Evaluate the configured basin-area criterion."""

    evidence = {
        "target_area_km2": config.target_area_km2,
        "preferred_area_km2": config.preferred_area_km2,
        "score_half_width_fraction": config.score_half_width_fraction,
        "hard_min_area_km2": config.hard_min_area_km2,
        "hard_max_area_km2": config.hard_max_area_km2,
        "ranges": [_area_range_record(area_range) for area_range in _area_ranges(config)],
    }
    if area_km2 is None:
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="area",
            criterion_family="geometry",
            criterion_mode=config.mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="missing",
            blocking=config.mode == "hard_reject",
            reason="area_km2 is missing",
            evidence_json=evidence,
        )

    if config.mode == "report_only":
        return _area_component(
            site_id=site_id,
            selection_principle=selection_principle,
            config=config,
            area_km2=area_km2,
            evaluation_order=evaluation_order,
            criterion_status="reported",
            reason="area reported without automatic decision",
            evidence=evidence,
        )

    if config.mode == "hard_reject":
        failed_reason = _area_range_failure_reason(area_km2, config)
        return _area_component(
            site_id=site_id,
            selection_principle=selection_principle,
            config=config,
            area_km2=area_km2,
            evaluation_order=evaluation_order,
            criterion_status="failed" if failed_reason else "passed",
            blocking=bool(failed_reason),
            reason=failed_reason or "area is inside configured hard bounds",
            threshold=_area_threshold_label(config),
            evidence=evidence,
        )

    if config.mode == "score":
        assert config.preferred_area_km2 is not None
        assert config.score_half_width_fraction is not None
        half_width = config.preferred_area_km2 * config.score_half_width_fraction
        normalized = abs(area_km2 - config.preferred_area_km2) / half_width
        score = max(0.0, 1.0 - normalized)
        return _area_component(
            site_id=site_id,
            selection_principle=selection_principle,
            config=config,
            area_km2=area_km2,
            evaluation_order=evaluation_order,
            criterion_status="scored",
            normalized_value=normalized,
            score_component=score,
            reason="area scored against preferred_area_km2",
            threshold=f"preferred={config.preferred_area_km2}; half_width={half_width}",
            evidence=evidence,
        )

    if config.mode == "warning":
        failed_reason = _area_range_failure_reason(area_km2, config)
        return _area_component(
            site_id=site_id,
            selection_principle=selection_principle,
            config=config,
            area_km2=area_km2,
            evaluation_order=evaluation_order,
            criterion_status="warning" if failed_reason else "passed",
            reason=failed_reason or "area does not trigger a warning",
            threshold=_area_threshold_label(config),
            evidence=evidence,
        )

    if config.mode == "stratify":
        return _area_component(
            site_id=site_id,
            selection_principle=selection_principle,
            config=config,
            area_km2=area_km2,
            evaluation_order=evaluation_order,
            criterion_status="stratified",
            reason="area available for stratification",
            evidence=evidence,
        )

    raise ValueError(f"Unsupported area criterion mode: {config.mode!r}")


def evaluate_flow_station_criterion(
    *,
    site_id: str,
    attributes: dict[str, Any],
    config: ObservationsCriteriaConfig,
    selection_principle: str,
    evaluation_order: int,
) -> CriteriaComponent:
    """Evaluate flow-station evidence attached to a candidate outlet.

    This function consumes normalized attributes that may come from Hub'Eau
    hydrometry through existing data managers, or from an imported candidate
    table. It does not fetch provider data itself.
    """

    detail = config.flow_station
    mode = detail.mode
    if mode == "report_only" and config.flow_station_mode != "report_only":
        mode = config.flow_station_mode
    record_years = _first_number(
        attributes,
        "record_years",
        "flow_station_record_years",
        "station_record_years",
    )
    n_records = _first_number(attributes, "n_records", "flow_station_n_records")
    if record_years is None and n_records is not None:
        record_years = n_records / 365.25

    distance_km = _first_number(
        attributes,
        "station_to_outlet_distance_km",
        "flow_station_distance_km",
        "hydro_station_distance_km",
    )
    station_inside = _first_bool(
        attributes,
        "station_inside_or_at_outlet",
        "flow_station_inside_or_at_outlet",
        "station_inside_basin",
    )
    max_distance_km = (
        detail.max_station_to_outlet_distance_km or config.flow_station_max_distance_km
    )
    evidence = {
        "record_years": record_years,
        "n_records": n_records,
        "station_to_outlet_distance_km": distance_km,
        "station_inside_or_at_outlet": station_inside,
        "min_record_years": detail.min_record_years,
        "max_station_to_outlet_distance_km": max_distance_km,
        "source_feature_id": attributes.get("source_feature_id"),
        "provider_source": attributes.get("provider_source"),
    }
    failures = []
    if detail.min_record_years is not None:
        if record_years is None:
            failures.append("record length is missing")
        elif record_years < detail.min_record_years:
            failures.append(
                f"record length {record_years:g} years is below {detail.min_record_years:g}"
            )
    if max_distance_km is not None:
        if distance_km is None:
            failures.append("station-to-outlet distance is missing")
        elif distance_km > max_distance_km:
            failures.append(
                f"station-to-outlet distance {distance_km:g} km exceeds {max_distance_km:g}"
            )
    if detail.require_station_inside_or_at_outlet and station_inside is False:
        failures.append("station is not flagged inside or at the outlet")

    has_evidence = any(value is not None and value != "" for value in (record_years, n_records, distance_km))
    if mode == "report_only":
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="flow_station",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="reported" if has_evidence else "missing",
            raw_value=record_years,
            reason=(
                "flow-station evidence reported without automatic decision"
                if has_evidence
                else "flow-station evidence is missing"
            ),
            evidence_json=evidence,
        )

    if mode == "score":
        score_parts = []
        if detail.min_record_years is not None and record_years is not None:
            score_parts.append(min(1.0, record_years / detail.min_record_years))
        if max_distance_km is not None and distance_km is not None:
            score_parts.append(max(0.0, 1.0 - distance_km / max_distance_km))
        score = sum(score_parts) / len(score_parts) if score_parts else None
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="flow_station",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="scored" if score is not None else "missing",
            raw_value=record_years,
            threshold=_flow_station_threshold_label(detail.min_record_years, max_distance_km),
            weight=1.0,
            score_component=score,
            reason=(
                "flow-station evidence scored"
                if score is not None
                else "flow-station evidence is missing for score mode"
            ),
            evidence_json=evidence,
        )

    if mode == "stratify":
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="flow_station",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="stratified" if has_evidence else "missing",
            raw_value=record_years,
            reason=(
                "flow-station evidence available for stratification"
                if has_evidence
                else "flow-station evidence is missing"
            ),
            evidence_json=evidence,
        )

    failed = bool(failures)
    status = "passed"
    if failed:
        status = "failed" if mode == "hard_reject" else "warning"
    elif not has_evidence:
        status = "missing"
    return CriteriaComponent(
        site_id=site_id,
        selection_principle=selection_principle,
        criterion_id="flow_station",
        criterion_family="observations",
        criterion_mode=mode,
        evaluation_stage="criteria",
        evaluation_order=evaluation_order,
        criterion_status=status,
        raw_value=record_years,
        threshold=_flow_station_threshold_label(detail.min_record_years, max_distance_km),
        blocking=failed and mode == "hard_reject",
        reason="; ".join(failures) if failures else "flow-station checks passed",
        evidence_json=evidence,
    )


def evaluate_piezometer_criterion(
    *,
    site_id: str,
    attributes: dict[str, Any],
    config: ObservationsCriteriaConfig,
    selection_principle: str,
    evaluation_order: int,
) -> CriteriaComponent:
    """Evaluate piezometer evidence attached to a candidate basin."""

    mode = config.piezometer_mode
    distance_km = _first_number(
        attributes,
        "piezometer_distance_km",
        "nearest_piezometer_distance_km",
        "piezometer_to_outlet_distance_km",
    )
    count = _first_number(
        attributes,
        "piezometer_count",
        "nearby_piezometer_count",
        "piezometers_in_basin",
    )
    inside = _first_bool(
        attributes,
        "piezometer_inside_basin",
        "has_piezometer_inside_basin",
    )
    max_distance_km = config.piezometer_max_distance_km
    has_evidence = (
        (count is not None and count > 0.0)
        or distance_km is not None
        or inside is True
    )
    evidence = {
        "piezometer_count": count,
        "nearest_piezometer_distance_km": distance_km,
        "piezometer_inside_basin": inside,
        "piezometer_max_distance_km": max_distance_km,
    }

    if mode == "report_only":
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="piezometer",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="reported" if has_evidence else "missing",
            raw_value=count if count is not None else distance_km,
            reason=(
                "piezometer evidence reported without automatic decision"
                if has_evidence
                else "piezometer evidence is missing"
            ),
            evidence_json=evidence,
        )

    if mode == "score":
        score = None
        if max_distance_km is not None and distance_km is not None:
            score = max(0.0, 1.0 - distance_km / max_distance_km)
        elif count is not None:
            score = min(1.0, count)
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="piezometer",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="scored" if score is not None else "missing",
            raw_value=count if count is not None else distance_km,
            threshold=_distance_threshold_label(max_distance_km),
            weight=1.0 if score is not None else None,
            score_component=score,
            reason=(
                "piezometer evidence scored"
                if score is not None
                else "piezometer evidence is missing for score mode"
            ),
            evidence_json=evidence,
        )

    if mode == "stratify":
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="piezometer",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="stratified" if has_evidence else "missing",
            raw_value=count if count is not None else distance_km,
            reason=(
                "piezometer evidence available for stratification"
                if has_evidence
                else "piezometer evidence is missing"
            ),
            evidence_json=evidence,
        )

    failures = []
    if not has_evidence:
        failures.append("piezometer evidence is missing")
    if max_distance_km is not None:
        if distance_km is None:
            failures.append("piezometer distance is missing")
        elif distance_km > max_distance_km:
            failures.append(
                f"piezometer distance {distance_km:g} km exceeds {max_distance_km:g}"
            )
    failed = bool(failures)
    status = "passed"
    if failed:
        status = "failed" if mode == "hard_reject" else "warning"
    return CriteriaComponent(
        site_id=site_id,
        selection_principle=selection_principle,
        criterion_id="piezometer",
        criterion_family="observations",
        criterion_mode=mode,
        evaluation_stage="criteria",
        evaluation_order=evaluation_order,
        criterion_status=status,
        raw_value=count if count is not None else distance_km,
        threshold=_distance_threshold_label(max_distance_km),
        blocking=failed and mode == "hard_reject",
        reason="; ".join(failures) if failures else "piezometer checks passed",
        evidence_json=evidence,
    )


def evaluate_influence_criterion(
    *,
    site_id: str,
    attributes: dict[str, Any],
    config: InfluenceCriteriaConfig,
    selection_principle: str,
    evaluation_order: int,
) -> CriteriaComponent:
    """Evaluate explicit non-influence flags for a candidate basin."""

    flags = {
        "major_dam_upstream": _first_bool(
            attributes,
            "major_dam_upstream",
            "has_major_dam_upstream",
            "dam_upstream",
        ),
        "major_withdrawal_upstream": _first_bool(
            attributes,
            "major_withdrawal_upstream",
            "has_major_withdrawal_upstream",
            "withdrawal_upstream",
        ),
        "major_regulated_reach": _first_bool(
            attributes,
            "major_regulated_reach",
            "has_major_regulated_reach",
            "regulated_reach",
        ),
    }
    checks = {
        "major_dam_upstream": config.reject_major_dam_upstream,
        "major_withdrawal_upstream": config.reject_major_withdrawal_upstream,
        "major_regulated_reach": config.reject_major_regulated_reach,
    }
    failures = [key for key, enabled in checks.items() if enabled and flags.get(key) is True]
    has_evidence = any(value is not None for value in flags.values())
    if config.mode == "report_only":
        status = "reported" if has_evidence else "missing"
    elif failures:
        status = "failed" if config.mode == "hard_reject" else "warning"
    elif has_evidence:
        status = "passed"
    else:
        status = "missing"
    return CriteriaComponent(
        site_id=site_id,
        selection_principle=selection_principle,
        criterion_id="influence",
        criterion_family="anthropic_influence",
        criterion_mode=config.mode,
        evaluation_stage="criteria",
        evaluation_order=evaluation_order,
        criterion_status=status,
        raw_value=bool(failures) if has_evidence else None,
        threshold="non-influenced" if any(checks.values()) else "report_only",
        blocking=bool(failures) and config.mode == "hard_reject",
        reason=(
            f"configured rejection flags present: {', '.join(failures)}"
            if failures
            else (
                "influence evidence reported without automatic decision"
                if config.mode == "report_only"
                else "no configured influence rejection flag is present"
            )
        ),
        evidence_json={
            **flags,
            "reject_major_dam_upstream": config.reject_major_dam_upstream,
            "reject_major_withdrawal_upstream": config.reject_major_withdrawal_upstream,
            "reject_major_regulated_reach": config.reject_major_regulated_reach,
            "influence_search_radius_km": config.influence_search_radius_km,
        },
    )


def evaluate_geology_criterion(
    *,
    site_id: str,
    attributes: dict[str, Any],
    config: GeologyCriteriaConfig,
    selection_principle: str,
    evaluation_order: int,
) -> CriteriaComponent:
    """Report or score geology evidence attached to a candidate basin."""

    geology_value = _first_text(
        attributes,
        "geology_class",
        "dominant_geology",
        "lithology",
        "geology_unit",
        "brgm_code",
    )
    evidence = {
        "geology_class": geology_value,
        "prefer_diversity": config.prefer_diversity,
    }
    if config.mode == "score":
        score = 1.0 if geology_value else None
        status = "scored" if geology_value else "missing"
    elif config.mode == "stratify":
        score = None
        status = "stratified" if geology_value else "missing"
    elif config.mode == "report_only":
        score = None
        status = "reported" if geology_value else "missing"
    elif config.mode in {"hard_reject", "warning"}:
        score = None
        status = "reported" if geology_value else "missing"
    else:
        raise ValueError(f"Unsupported geology criterion mode: {config.mode!r}")

    return CriteriaComponent(
        site_id=site_id,
        selection_principle=selection_principle,
        criterion_id="geology",
        criterion_family="geology",
        criterion_mode=config.mode,
        evaluation_stage="criteria",
        evaluation_order=evaluation_order,
        criterion_status=status,
        raw_value=geology_value,
        weight=1.0 if score is not None else None,
        score_component=score,
        reason=(
            "geology evidence available"
            if geology_value
            else "geology evidence is missing or not loaded"
        ),
        evidence_json=evidence,
    )


def _area_component(
    *,
    site_id: str,
    selection_principle: str,
    config: AreaCriteriaConfig,
    area_km2: float,
    evaluation_order: int,
    criterion_status: str,
    reason: str,
    evidence: dict[str, Any],
    normalized_value: float | None = None,
    threshold: float | str | None = None,
    score_component: float | None = None,
    blocking: bool = False,
) -> CriteriaComponent:
    return CriteriaComponent(
        site_id=site_id,
        selection_principle=selection_principle,
        criterion_id="area",
        criterion_family="geometry",
        criterion_mode=config.mode,
        evaluation_stage="criteria",
        evaluation_order=evaluation_order,
        criterion_status=criterion_status,
        raw_value=float(area_km2),
        normalized_value=normalized_value,
        threshold=threshold,
        score_component=score_component,
        blocking=blocking,
        reason=reason,
        evidence_json=evidence,
    )


def _area_hard_failure_reason(area_km2: float, config: AreaCriteriaConfig) -> str:
    if config.hard_min_area_km2 is not None and area_km2 < config.hard_min_area_km2:
        return f"area {area_km2:g} km2 is below hard_min_area_km2 {config.hard_min_area_km2:g}"
    if config.hard_max_area_km2 is not None and area_km2 > config.hard_max_area_km2:
        return f"area {area_km2:g} km2 is above hard_max_area_km2 {config.hard_max_area_km2:g}"
    return ""


def _area_range_failure_reason(area_km2: float, config: AreaCriteriaConfig) -> str:
    if not config.ranges:
        return _area_hard_failure_reason(area_km2, config)
    ranges = _area_ranges(config)
    if not ranges:
        return _area_hard_failure_reason(area_km2, config)
    if any(
        area_range.min_area_km2 <= area_km2 <= area_range.max_area_km2
        for area_range in ranges
    ):
        return ""
    return f"area {area_km2:g} km2 is outside configured area ranges: {_area_threshold_label(config)}"


def _area_threshold_label(config: AreaCriteriaConfig) -> str:
    if config.ranges:
        ranges = _area_ranges(config)
        return "; ".join(_area_range_label(area_range) for area_range in ranges)
    return f"{config.hard_min_area_km2}..{config.hard_max_area_km2} km2"


def _area_ranges(config: AreaCriteriaConfig) -> list[AreaRangeConfig]:
    return list(config.ranges)


def _area_range_record(area_range: AreaRangeConfig) -> dict[str, float | str]:
    return {
        "range_id": area_range.range_id,
        "label": area_range.label,
        "min_area_km2": area_range.min_area_km2,
        "max_area_km2": area_range.max_area_km2,
    }


def _area_range_label(area_range: AreaRangeConfig) -> str:
    label = area_range.label or area_range.range_id
    bounds = f"{area_range.min_area_km2:g}-{area_range.max_area_km2:g} km2"
    return f"{label} ({bounds})" if label else bounds


def _flow_station_threshold_label(
    min_record_years: float | None,
    max_distance_km: float | None,
) -> str:
    parts = []
    if min_record_years is not None:
        parts.append(f"min_record_years={min_record_years:g}")
    if max_distance_km is not None:
        parts.append(f"max_distance_km={max_distance_km:g}")
    return "; ".join(parts)


def _distance_threshold_label(max_distance_km: float | None) -> str:
    return "" if max_distance_km is None else f"max_distance_km={max_distance_km:g}"


def _first_number(attributes: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = attributes.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_bool(attributes: dict[str, Any], *keys: str) -> bool | None:
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


def _first_text(attributes: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


__all__ = [
    "CriteriaComponent",
    "evaluate_area_criterion",
    "evaluate_flow_station_criterion",
    "evaluate_geology_criterion",
    "evaluate_influence_criterion",
    "evaluate_piezometer_criterion",
]
