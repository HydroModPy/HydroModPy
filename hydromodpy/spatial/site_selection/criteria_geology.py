"""Geology criterion evaluation."""

from __future__ import annotations

from typing import Any

from hydromodpy.spatial.site_selection.config import GeologyCriteriaConfig
from hydromodpy.spatial.site_selection.criteria_common import (
    CriteriaComponent,
    _first_text,
)
from hydromodpy.spatial.site_selection.evidence_refs import geology_evidence_ref


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
        "source_name": _first_text(attributes, "geology_source"),
        "evidence_ref": geology_evidence_ref(
            site_id=site_id,
            source_layer=_first_text(attributes, "geology_source"),
            geology_class=geology_value,
        ),
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


__all__ = ["evaluate_geology_criterion"]
