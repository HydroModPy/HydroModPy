"""Anthropic-influence criterion evaluation."""

from __future__ import annotations

from typing import Any

from hydromodpy.spatial.site_selection.config import InfluenceCriteriaConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.common import (
    CriteriaComponent,
    _first_bool,
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
    evidence_refs = _influence_refs_for_decision(
        attributes,
        failed_flags=failures,
    )
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
            "evidence_ref": evidence_refs[0] if evidence_refs else None,
            "evidence_refs": evidence_refs,
        },
    )


def _influence_refs_for_decision(
    attributes: dict[str, Any],
    *,
    failed_flags: list[str],
) -> list[str]:
    if failed_flags:
        refs = []
        for flag in failed_flags:
            refs.extend(_string_list(attributes.get(f"{flag}_evidence_refs")))
        if refs:
            return _stable_unique(refs)
    return _stable_unique(_string_list(attributes.get("influence_evidence_refs")))


def _string_list(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _stable_unique(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


__all__ = ["evaluate_influence_criterion"]
