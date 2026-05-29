"""Normalized decision records for site selection."""

from __future__ import annotations

from hydromodpy.spatial.site_selection.decisions.aggregate import (
    aggregate_site_selection_decisions,
)
from hydromodpy.spatial.site_selection.decisions.evidence import (
    evidence_records_from_geology_evidence,
    evidence_records_from_influence_evidence,
    evidence_records_from_observation_evidence,
    evidence_records_from_site_selection_evidence,
)
from hydromodpy.spatial.site_selection.decisions.exports import (
    SITE_DECISION_SUMMARY_FIELDS,
    write_decision_records_jsonl,
    write_evidence_records_jsonl,
    write_site_decision_summary_csv,
)
from hydromodpy.spatial.site_selection.decisions.models import (
    DecisionRecord,
    DecisionValue,
    EvidenceRecord,
    GlobalDecisionValue,
    MetricValue,
    SiteDecisionSummary,
)
from hydromodpy.spatial.site_selection.decisions.records import (
    decision_records_from_criteria_components,
    decision_records_from_selection_decisions,
    decision_records_from_selection_result,
)

__all__ = [
    "DecisionRecord",
    "DecisionValue",
    "EvidenceRecord",
    "GlobalDecisionValue",
    "MetricValue",
    "SITE_DECISION_SUMMARY_FIELDS",
    "SiteDecisionSummary",
    "aggregate_site_selection_decisions",
    "decision_records_from_criteria_components",
    "decision_records_from_selection_decisions",
    "decision_records_from_selection_result",
    "evidence_records_from_geology_evidence",
    "evidence_records_from_influence_evidence",
    "evidence_records_from_observation_evidence",
    "evidence_records_from_site_selection_evidence",
    "write_decision_records_jsonl",
    "write_evidence_records_jsonl",
    "write_site_decision_summary_csv",
]
