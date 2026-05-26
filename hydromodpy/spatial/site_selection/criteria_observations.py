"""Observation-based site-selection criteria."""

from __future__ import annotations

from typing import Any

from hydromodpy.spatial.site_selection.config import ObservationsCriteriaConfig
from hydromodpy.spatial.site_selection.criteria_common import (
    CriteriaComponent,
    _distance_threshold_label,
    _first_bool,
    _first_number,
    _first_text,
)
from hydromodpy.spatial.site_selection.evidence_refs import (
    observation_evidence_ref,
)
from hydromodpy.spatial.site_selection.station_influence import (
    station_influence_diagnostics,
)


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
    station_id = _first_text(
        attributes,
        "flow_station_id",
        "hydro_station_id",
        "station_id",
        "source_feature_id",
    )
    evidence = {
        "record_years": record_years,
        "n_records": n_records,
        "station_to_outlet_distance_km": distance_km,
        "station_inside_or_at_outlet": station_inside,
        "min_record_years": detail.min_record_years,
        "max_station_to_outlet_distance_km": max_distance_km,
        "source_feature_id": station_id,
        "provider_source": attributes.get("provider_source"),
        "evidence_ref": observation_evidence_ref(
            site_id=site_id,
            observation_type="flow_station",
            feature_id=station_id,
        ),
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

    has_evidence = any(
        value is not None and value != ""
        for value in (record_years, n_records, distance_km)
    )
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
            threshold=_flow_station_threshold_label(
                detail.min_record_years,
                max_distance_km,
            ),
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


def evaluate_station_influence_criterion(
    *,
    site_id: str,
    attributes: dict[str, Any],
    config: ObservationsCriteriaConfig,
    selection_principle: str,
    evaluation_order: int,
) -> CriteriaComponent:
    """Evaluate hydrologic influence metadata attached to a flow station."""

    detail = config.station_influence
    mode = detail.mode
    diagnostics = station_influence_diagnostics(
        attributes,
        comment_keywords=detail.comment_keywords,
    )
    station_id = _first_text(
        attributes,
        "flow_station_id",
        "hydro_station_id",
        "station_id",
        "source_feature_id",
    )
    evidence = {
        "source_dataset": detail.source,
        "provider_source": attributes.get("provider_source"),
        "source_feature_id": station_id,
        "station_influence_status": diagnostics.status,
        "station_influence_flags": list(diagnostics.flags),
        "station_influence_raw_fields": dict(diagnostics.raw_fields),
        "matched_keywords": list(diagnostics.matched_keywords),
        "unknown_policy": detail.unknown_policy,
        "evidence_ref": observation_evidence_ref(
            site_id=site_id,
            observation_type="flow_station",
            feature_id=station_id,
        ),
    }
    has_evidence = diagnostics.has_raw_evidence
    issues = _station_influence_issues(
        status=diagnostics.status,
        flags=diagnostics.flags,
        has_evidence=has_evidence,
        detail=detail,
    )

    if mode == "report_only":
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="station_influence",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="reported" if has_evidence else "missing",
            raw_value=diagnostics.status,
            reason=(
                "station influence metadata reported without automatic decision"
                if has_evidence
                else "station influence metadata is missing"
            ),
            evidence_json=evidence,
        )

    if mode == "score":
        score = _station_influence_score(diagnostics.status)
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="station_influence",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="scored" if has_evidence else "missing",
            raw_value=diagnostics.status,
            threshold="non_influenced_station",
            weight=1.0 if has_evidence else None,
            score_component=score if has_evidence else None,
            reason=(
                "station influence metadata scored"
                if has_evidence
                else "station influence metadata is missing for score mode"
            ),
            evidence_json=evidence,
        )

    if mode == "stratify":
        return CriteriaComponent(
            site_id=site_id,
            selection_principle=selection_principle,
            criterion_id="station_influence",
            criterion_family="observations",
            criterion_mode=mode,
            evaluation_stage="criteria",
            evaluation_order=evaluation_order,
            criterion_status="stratified" if has_evidence else "missing",
            raw_value=diagnostics.status,
            reason=(
                "station influence metadata available for stratification"
                if has_evidence
                else "station influence metadata is missing"
            ),
            evidence_json=evidence,
        )

    failed = bool(issues)
    if failed:
        status = "failed" if mode == "hard_reject" else "warning"
    elif diagnostics.status == "no_known_influence":
        status = "passed"
    elif not has_evidence:
        status = "missing"
    else:
        status = "reported"
    return CriteriaComponent(
        site_id=site_id,
        selection_principle=selection_principle,
        criterion_id="station_influence",
        criterion_family="observations",
        criterion_mode=mode,
        evaluation_stage="criteria",
        evaluation_order=evaluation_order,
        criterion_status=status,
        raw_value=diagnostics.status,
        threshold="non_influenced_station",
        blocking=failed and mode == "hard_reject",
        reason=(
            "; ".join(issues)
            if issues
            else _station_influence_pass_reason(diagnostics.status, has_evidence)
        ),
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
    piezometer_id = _first_text(
        attributes,
        "piezometer_id",
        "nearest_piezometer_id",
    )
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
        "piezometer_id": piezometer_id,
        "evidence_ref": observation_evidence_ref(
            site_id=site_id,
            observation_type="piezometer",
            feature_id=piezometer_id,
        ),
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


def _station_influence_issues(
    *,
    status: str,
    flags: list[str],
    has_evidence: bool,
    detail: Any,
) -> list[str]:
    issues: list[str] = []
    if status == "general_influence" and detail.warn_if_general_influence:
        issues.append("station has general hydrologic influence metadata")
    elif status == "local_influence" and detail.warn_if_local_influence:
        issues.append("station has local hydrologic influence metadata")

    if detail.warn_if_comment_keyword and any(flag.endswith("_keyword") for flag in flags):
        if not issues:
            issues.append("station comments mention possible hydraulic influence")

    if not has_evidence and detail.unknown_policy == "warning":
        issues.append("station influence metadata is missing")
    elif status == "unknown" and detail.unknown_policy == "warning":
        issues.append("station influence status is unknown")
    return issues


def _station_influence_score(status: str) -> float:
    if status == "no_known_influence":
        return 1.0
    if status == "unknown":
        return 0.5
    return 0.0


def _station_influence_pass_reason(status: str, has_evidence: bool) -> str:
    if status == "no_known_influence":
        return "station influence metadata reports no known influence"
    if not has_evidence:
        return "station influence metadata is missing"
    if status == "unknown":
        return "station influence status is unknown"
    return "station influence metadata reported"


__all__ = [
    "evaluate_flow_station_criterion",
    "evaluate_piezometer_criterion",
    "evaluate_station_influence_criterion",
]
