"""Basin-area criterion evaluation."""

from __future__ import annotations

from typing import Any

from hydromodpy.spatial.site_selection.config import AreaCriteriaConfig, AreaRangeConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.common import CriteriaComponent


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
    if any(area_range.min_area_km2 <= area_km2 <= area_range.max_area_km2 for area_range in ranges):
        return ""
    return (
        f"area {area_km2:g} km2 is outside configured area ranges: {_area_threshold_label(config)}"
    )


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


__all__ = ["evaluate_area_criterion"]
