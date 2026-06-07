"""Aggregation helpers for site-selection decision records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from hydromodpy.spatial.site_selection.decisions.models import (
    DecisionRecord,
    GlobalDecisionValue,
    SiteDecisionSummary,
)


def aggregate_site_selection_decisions(
    records: Iterable[DecisionRecord],
) -> list[SiteDecisionSummary]:
    """Aggregate detailed decision records into one summary per catchment."""

    grouped: dict[tuple[str, str], list[DecisionRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.run_id, record.catchment_id)].append(record)

    summaries = []
    for (run_id, catchment_id), catchment_records in sorted(grouped.items()):
        summaries.append(
            SiteDecisionSummary(
                run_id=run_id,
                catchment_id=catchment_id,
                global_decision=_global_decision(catchment_records),
                n_accept=sum(1 for record in catchment_records if record.decision == "ACCEPT"),
                n_warning=sum(1 for record in catchment_records if record.decision == "WARNING"),
                n_reject=sum(1 for record in catchment_records if record.decision == "REJECT"),
                n_neutral=sum(1 for record in catchment_records if record.decision == "NEUTRAL"),
                reject_reasons=_reasons(catchment_records, decision="REJECT"),
                warning_reasons=_reasons(catchment_records, decision="WARNING"),
                evidence_refs=_evidence_refs(catchment_records),
            )
        )
    return summaries


def _global_decision(records: list[DecisionRecord]) -> GlobalDecisionValue:
    if any(record.decision == "REJECT" for record in records):
        return "REJECT"
    if any(record.decision == "WARNING" for record in records):
        return "ACCEPT_WITH_WARNINGS"
    if any(record.decision == "ACCEPT" for record in records):
        return "ACCEPT"
    return "NEUTRAL"


def _reasons(records: list[DecisionRecord], *, decision: str) -> list[str]:
    return _stable_unique(
        _reason_label(record) for record in records if record.decision == decision
    )


def _reason_label(record: DecisionRecord) -> str:
    if record.message:
        return f"{record.criterion_id}: {record.message}"
    return record.criterion_id


def _evidence_refs(records: list[DecisionRecord]) -> list[str]:
    return _stable_unique(
        str(record.evidence_ref) for record in records if record.evidence_ref not in (None, "")
    )


def _stable_unique(values: Iterable[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


__all__ = ["aggregate_site_selection_decisions"]
