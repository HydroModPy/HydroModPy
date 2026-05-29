"""Typed decision and evidence records for site selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DecisionValue = Literal["ACCEPT", "WARNING", "REJECT", "NEUTRAL"]
GlobalDecisionValue = Literal["ACCEPT", "ACCEPT_WITH_WARNINGS", "REJECT", "NEUTRAL"]
MetricValue = float | int | str | bool | None


@dataclass(frozen=True)
class DecisionRecord:
    """One auditable decision contribution for one catchment."""

    run_id: str
    catchment_id: str
    criterion_family: str
    criterion_id: str
    decision: DecisionValue
    severity: int | None = None
    metric_name: str | None = None
    metric_value: MetricValue = None
    threshold_value: MetricValue = None
    source_name: str | None = None
    source_version: str | None = None
    evidence_ref: str | None = None
    message: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a JSONL-friendly mapping."""

        return {
            "run_id": self.run_id,
            "catchment_id": self.catchment_id,
            "criterion_family": self.criterion_family,
            "criterion_id": self.criterion_id,
            "decision": self.decision,
            "severity": self.severity,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold_value": self.threshold_value,
            "source_name": self.source_name,
            "source_version": self.source_version,
            "evidence_ref": self.evidence_ref,
            "message": self.message,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True)
class EvidenceRecord:
    """One normalized evidence feature linked to a decision criterion."""

    run_id: str
    evidence_ref: str
    catchment_id: str
    criterion_family: str
    criterion_id: str
    source_name: str | None = None
    source_version: str | None = None
    feature_id: str | None = None
    feature_label: str | None = None
    geometry: object | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-friendly mapping.

        Geometry is kept as GeoJSON-like data when a Shapely geometry is passed.
        """

        geometry = self.geometry
        if hasattr(geometry, "__geo_interface__"):
            geometry = geometry.__geo_interface__
        return {
            "run_id": self.run_id,
            "evidence_ref": self.evidence_ref,
            "catchment_id": self.catchment_id,
            "criterion_family": self.criterion_family,
            "criterion_id": self.criterion_id,
            "source_name": self.source_name,
            "source_version": self.source_version,
            "feature_id": self.feature_id,
            "feature_label": self.feature_label,
            "geometry": geometry,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True)
class SiteDecisionSummary:
    """Aggregated decision for one catchment."""

    run_id: str
    catchment_id: str
    global_decision: GlobalDecisionValue
    n_accept: int = 0
    n_warning: int = 0
    n_reject: int = 0
    n_neutral: int = 0
    reject_reasons: list[str] = field(default_factory=list)
    warning_reasons: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-friendly mapping."""

        return {
            "run_id": self.run_id,
            "catchment_id": self.catchment_id,
            "global_decision": self.global_decision,
            "n_accept": self.n_accept,
            "n_warning": self.n_warning,
            "n_reject": self.n_reject,
            "n_neutral": self.n_neutral,
            "reject_reasons": list(self.reject_reasons),
            "warning_reasons": list(self.warning_reasons),
            "evidence_refs": list(self.evidence_refs),
        }

    def to_csv_record(self) -> dict[str, Any]:
        """Return a compact CSV-friendly mapping."""

        return {
            "run_id": self.run_id,
            "catchment_id": self.catchment_id,
            "global_decision": self.global_decision,
            "n_accept": self.n_accept,
            "n_warning": self.n_warning,
            "n_reject": self.n_reject,
            "n_neutral": self.n_neutral,
            "reject_reasons": "; ".join(self.reject_reasons),
            "warning_reasons": "; ".join(self.warning_reasons),
            "evidence_refs": "; ".join(self.evidence_refs),
        }


__all__ = [
    "DecisionRecord",
    "DecisionValue",
    "EvidenceRecord",
    "GlobalDecisionValue",
    "MetricValue",
    "SiteDecisionSummary",
]
