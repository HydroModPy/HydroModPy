"""Build normalized decision records from selection results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hydromodpy.spatial.site_selection.decisions.models import (
    DecisionRecord,
    DecisionValue,
    MetricValue,
)
from hydromodpy.spatial.site_selection.evaluation.criteria import CriteriaComponent
from hydromodpy.spatial.site_selection.evaluation.selection import (
    SelectionDecision,
    SelectionResult,
)

_DECISION_SEVERITY: dict[DecisionValue, int] = {
    "NEUTRAL": 0,
    "ACCEPT": 1,
    "WARNING": 2,
    "REJECT": 3,
}


def decision_records_from_selection_result(
    result: SelectionResult,
    *,
    run_id: str,
    include_final_selection: bool = True,
) -> list[DecisionRecord]:
    """Convert a current ``SelectionResult`` into normalized decision records."""

    records = decision_records_from_criteria_components(
        result.criteria_components,
        run_id=run_id,
    )
    if include_final_selection:
        records.extend(
            decision_records_from_selection_decisions(result.decisions, run_id=run_id)
        )
    return sorted(
        records,
        key=lambda record: (
            record.catchment_id,
            int(record.properties.get("evaluation_order") or 10_000),
            record.criterion_family,
            record.criterion_id,
        ),
    )


def decision_records_from_criteria_components(
    components: Iterable[CriteriaComponent],
    *,
    run_id: str,
) -> list[DecisionRecord]:
    """Convert auditable criterion components into decision records."""

    return [_record_from_component(component, run_id=run_id) for component in components]


def decision_records_from_selection_decisions(
    decisions: Iterable[SelectionDecision],
    *,
    run_id: str,
) -> list[DecisionRecord]:
    """Convert final site-selection decisions into decision records."""

    return [_record_from_selection_decision(decision, run_id=run_id) for decision in decisions]


def _record_from_component(component: CriteriaComponent, *, run_id: str) -> DecisionRecord:
    decision = _component_decision(component)
    evidence = dict(component.evidence_json)
    return DecisionRecord(
        run_id=run_id,
        catchment_id=component.site_id,
        criterion_family=component.criterion_family,
        criterion_id=component.criterion_id,
        decision=decision,
        severity=_DECISION_SEVERITY[decision],
        metric_name=component.criterion_id,
        metric_value=_metric_value(component.raw_value),
        threshold_value=_metric_value(component.threshold),
        source_name=_first_text(
            evidence,
            "source_name",
            "source_dataset",
            "provider_source",
            "source",
            "reference_network_source",
        ),
        source_version=_first_text(evidence, "source_version", "provider_version"),
        evidence_ref=_first_text(evidence, "evidence_ref", "evidence_id"),
        message=component.reason or None,
        properties={
            "selection_principle": component.selection_principle,
            "criterion_mode": component.criterion_mode,
            "evaluation_stage": component.evaluation_stage,
            "evaluation_order": component.evaluation_order,
            "criterion_status": component.criterion_status,
            "normalized_value": component.normalized_value,
            "weight": component.weight,
            "score_component": component.score_component,
            "blocking": component.blocking,
            "evidence_json": evidence,
        },
    )


def _record_from_selection_decision(
    decision: SelectionDecision,
    *,
    run_id: str,
) -> DecisionRecord:
    value: DecisionValue = "ACCEPT" if decision.selected else "REJECT"
    return DecisionRecord(
        run_id=run_id,
        catchment_id=decision.site_id,
        criterion_family="selection",
        criterion_id="final_selection",
        decision=value,
        severity=_DECISION_SEVERITY[value],
        metric_name="selected",
        metric_value=decision.selected,
        threshold_value=True,
        message=decision.decision_reason or None,
        properties={
            "selection_principle": decision.selection_principle,
            "decision_stage": decision.decision_stage,
            "blocking_flags": list(decision.blocking_flags),
            "warning_flags": list(decision.warning_flags),
            "rank_score": decision.rank_score,
            "stratification_class": decision.stratification_class,
            "criteria_summary_json": dict(decision.criteria_summary_json),
        },
    )


def _component_decision(component: CriteriaComponent) -> DecisionValue:
    status = component.criterion_status
    if component.blocking or status == "failed":
        return "REJECT"
    if status == "warning":
        return "WARNING"
    if status == "passed":
        return "ACCEPT"
    return "NEUTRAL"


def _metric_value(value: object) -> MetricValue:
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _first_text(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


__all__ = [
    "decision_records_from_criteria_components",
    "decision_records_from_selection_decisions",
    "decision_records_from_selection_result",
]
