"""Exports for normalized site-selection decision records."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hydromodpy.spatial.site_selection.decisions.models import (
    DecisionRecord,
    EvidenceRecord,
    SiteDecisionSummary,
)
from hydromodpy.spatial.site_selection.outputs.tabular import write_csv, write_jsonl

SITE_DECISION_SUMMARY_FIELDS = [
    "run_id",
    "catchment_id",
    "global_decision",
    "n_accept",
    "n_warning",
    "n_reject",
    "n_neutral",
    "reject_reasons",
    "warning_reasons",
    "evidence_refs",
]


def write_decision_records_jsonl(
    path: str | Path,
    records: Iterable[DecisionRecord],
) -> Path:
    """Write detailed decision records as JSON Lines."""

    return write_jsonl(path, [record.to_record() for record in records])


def write_evidence_records_jsonl(
    path: str | Path,
    records: Iterable[EvidenceRecord],
) -> Path:
    """Write normalized evidence records as JSON Lines."""

    return write_jsonl(path, [record.to_record() for record in records])


def write_site_decision_summary_csv(
    path: str | Path,
    summaries: Iterable[SiteDecisionSummary],
) -> Path:
    """Write one decision summary row per catchment."""

    return write_csv(
        path,
        [summary.to_csv_record() for summary in summaries],
        fieldnames=SITE_DECISION_SUMMARY_FIELDS,
    )


__all__ = [
    "SITE_DECISION_SUMMARY_FIELDS",
    "write_decision_records_jsonl",
    "write_evidence_records_jsonl",
    "write_site_decision_summary_csv",
]
