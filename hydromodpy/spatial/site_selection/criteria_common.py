"""Shared primitives for site-selection criteria."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
]
