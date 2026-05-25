"""Selection decisions for delineated candidate catchments."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from hydromodpy.spatial.site_selection.config import CriteriaConfig, SpatialSelectionConfig
from hydromodpy.spatial.site_selection.criteria import (
    CriteriaComponent,
    evaluate_area_criterion,
    evaluate_flow_station_criterion,
    evaluate_geology_criterion,
    evaluate_influence_criterion,
    evaluate_piezometer_criterion,
)
from hydromodpy.spatial.site_selection.delineation import (
    DelineatedCatchment,
    outlet_display_xy,
    outlet_snap_distance_m,
)
from hydromodpy.spatial.site_selection.filters import basin_overlap_fraction, is_overlap_allowed


@dataclass(frozen=True)
class SelectionDecision:
    """Final decision for one candidate site."""

    site_id: str
    selection_principle: str
    selected: bool
    decision_stage: str
    decision_reason: str
    blocking_flags: list[str] = field(default_factory=list)
    warning_flags: list[str] = field(default_factory=list)
    rank_score: float | None = None
    stratification_class: str = ""
    criteria_summary_json: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a JSON/parquet-friendly mapping."""

        return {
            "site_id": self.site_id,
            "selection_principle": self.selection_principle,
            "selected": self.selected,
            "decision_stage": self.decision_stage,
            "decision_reason": self.decision_reason,
            "blocking_flags": list(self.blocking_flags),
            "warning_flags": list(self.warning_flags),
            "rank_score": self.rank_score,
            "stratification_class": self.stratification_class,
            "criteria_summary_json": dict(self.criteria_summary_json),
        }


@dataclass(frozen=True)
class SelectionResult:
    """Selected/rejected catchments and their audit trail."""

    selected: list[DelineatedCatchment]
    rejected: list[DelineatedCatchment]
    decisions: list[SelectionDecision]
    criteria_components: list[CriteriaComponent]


def select_delineated_catchments(
    catchments: list[DelineatedCatchment],
    *,
    criteria: CriteriaConfig,
    spatial_selection: SpatialSelectionConfig,
    selection_principle: str,
    basin_geometries: dict[str, object] | None = None,
) -> SelectionResult:
    """Apply area and overlap decisions to already delineated catchments."""

    geometries = basin_geometries or {}
    selected: list[DelineatedCatchment] = []
    rejected: list[DelineatedCatchment] = []
    decisions: list[SelectionDecision] = []
    components: list[CriteriaComponent] = []

    scored: list[tuple[DelineatedCatchment, list[CriteriaComponent], float]] = []
    for catchment in catchments:
        if catchment.status != "delineated":
            rejected.append(catchment)
            decisions.append(
                SelectionDecision(
                    site_id=catchment.site_id,
                    selection_principle=selection_principle,
                    selected=False,
                    decision_stage="delineation",
                    decision_reason=catchment.failure_reason or catchment.status,
                    blocking_flags=[catchment.status],
                    rank_score=None,
                )
            )
            continue

        area_component = evaluate_area_criterion(
            site_id=catchment.site_id,
            area_km2=catchment.area_km2,
            config=criteria.area,
            selection_principle=selection_principle,
            evaluation_order=0,
        )
        attributes = _catchment_attributes(catchment)
        catchment_components = [
            area_component,
            evaluate_flow_station_criterion(
                site_id=catchment.site_id,
                attributes=attributes,
                config=criteria.observations,
                selection_principle=selection_principle,
                evaluation_order=1,
            ),
            evaluate_piezometer_criterion(
                site_id=catchment.site_id,
                attributes=attributes,
                config=criteria.observations,
                selection_principle=selection_principle,
                evaluation_order=2,
            ),
            evaluate_influence_criterion(
                site_id=catchment.site_id,
                attributes=attributes,
                config=criteria.influence,
                selection_principle=selection_principle,
                evaluation_order=3,
            ),
            evaluate_geology_criterion(
                site_id=catchment.site_id,
                attributes=attributes,
                config=criteria.geology,
                selection_principle=selection_principle,
                evaluation_order=4,
            ),
        ]
        components.extend(catchment_components)
        blocking_component = next(
            (component for component in catchment_components if component.blocking),
            None,
        )
        if blocking_component is not None:
            rejected.append(catchment)
            decisions.append(
                _decision_from_components(
                    catchment=catchment,
                    selection_principle=selection_principle,
                    selected=False,
                    decision_stage="criteria",
                    decision_reason=blocking_component.reason,
                    components=catchment_components,
                    rank_score=None,
                )
            )
            continue

        score = float(catchment.outlet.priority)
        for component in catchment_components:
            if component.score_component is not None:
                score += float(component.score_component)
        scored.append((catchment, catchment_components, score))

    for catchment, catchment_components, score in sorted(
        scored,
        key=lambda item: (-item[2], item[0].site_id),
    ):
        overlap_component = _overlap_component(
            catchment=catchment,
            selected=selected,
            geometries=geometries,
            spatial_selection=spatial_selection,
            selection_principle=selection_principle,
            evaluation_order=len(catchment_components),
        )
        if overlap_component is not None:
            catchment_components = [*catchment_components, overlap_component]
            components.append(overlap_component)

        if overlap_component is not None and overlap_component.blocking:
            rejected.append(catchment)
            decisions.append(
                _decision_from_components(
                    catchment=catchment,
                    selection_principle=selection_principle,
                    selected=False,
                    decision_stage="spatial_selection",
                    decision_reason=overlap_component.reason,
                    components=catchment_components,
                    rank_score=score,
                )
            )
            continue

        selected.append(catchment)
        decisions.append(
            _decision_from_components(
                catchment=catchment,
                selection_principle=selection_principle,
                selected=True,
                decision_stage="selection",
                decision_reason="selected",
                components=catchment_components,
                rank_score=score,
            )
        )

    decisions.sort(key=lambda decision: decision.site_id)
    return SelectionResult(
        selected=sorted(selected, key=lambda catchment: catchment.site_id),
        rejected=sorted(rejected, key=lambda catchment: catchment.site_id),
        decisions=decisions,
        criteria_components=components,
    )


def _overlap_component(
    *,
    catchment: DelineatedCatchment,
    selected: list[DelineatedCatchment],
    geometries: dict[str, object],
    spatial_selection: SpatialSelectionConfig,
    selection_principle: str,
    evaluation_order: int,
) -> CriteriaComponent | None:
    max_allowed = spatial_selection.max_pairwise_basin_overlap_fraction
    if max_allowed is None or not selected:
        return None
    candidate_geometry = geometries.get(catchment.site_id)
    if candidate_geometry is None:
        return None

    max_overlap = 0.0
    max_overlap_site_id = ""
    for selected_catchment in selected:
        selected_geometry = geometries.get(selected_catchment.site_id)
        if selected_geometry is None:
            continue
        overlap = basin_overlap_fraction(
            candidate_geometry=candidate_geometry,
            selected_geometry=selected_geometry,
            reference=spatial_selection.overlap_reference,
        )
        if overlap > max_overlap:
            max_overlap = overlap
            max_overlap_site_id = selected_catchment.site_id

    allowed = is_overlap_allowed(
        overlap_fraction=max_overlap,
        max_pairwise_basin_overlap_fraction=max_allowed,
    )
    mode = spatial_selection.overlap_mode
    blocking = (not allowed) and mode == "hard_reject"
    status = "passed" if allowed else ("failed" if blocking else "warning")
    reason = (
        "overlap is below configured threshold"
        if allowed
        else (
            f"overlap {max_overlap:.3f} with {max_overlap_site_id} exceeds "
            f"{max_allowed:.3f}"
        )
    )
    return CriteriaComponent(
        site_id=catchment.site_id,
        selection_principle=selection_principle,
        criterion_id="basin_overlap",
        criterion_family="spatial_selection",
        criterion_mode=mode,
        evaluation_stage="spatial_selection",
        evaluation_order=evaluation_order,
        criterion_status=status,
        raw_value=max_overlap,
        threshold=max_allowed,
        blocking=blocking,
        reason=reason,
        evidence_json={
            "max_overlap_site_id": max_overlap_site_id,
            "overlap_reference": spatial_selection.overlap_reference,
        },
    )


def _catchment_attributes(catchment: DelineatedCatchment) -> dict[str, Any]:
    attributes = dict(catchment.outlet.attributes)
    attributes.setdefault("source_feature_id", catchment.outlet.source_feature_id)
    attributes.setdefault("source_label", catchment.outlet.source_label)
    attributes.setdefault("source", catchment.outlet.source)
    snap_distance_m = outlet_snap_distance_m(catchment)
    if snap_distance_m is not None:
        attributes["outlet_snap_distance_m"] = snap_distance_m
        attributes["outlet_snap_distance_km"] = snap_distance_m / 1000.0
    station_distance_km = _station_to_final_outlet_distance_km(catchment, attributes)
    if station_distance_km is not None:
        attributes["station_to_outlet_distance_km"] = station_distance_km
        attributes["flow_station_distance_km"] = station_distance_km
        attributes["hydro_station_distance_km"] = station_distance_km
        attributes["station_to_outlet_distance_source"] = "computed_from_final_outlet"
    return attributes


def _station_to_final_outlet_distance_km(
    catchment: DelineatedCatchment,
    attributes: dict[str, Any],
) -> float | None:
    station = _flow_station_xy(attributes, target_crs=catchment.outlet.crs)
    if station is None and _looks_station_led(catchment, attributes):
        station = (float(catchment.outlet.x), float(catchment.outlet.y))
    if station is None:
        return None
    outlet = outlet_display_xy(catchment)
    return math.hypot(station[0] - outlet[0], station[1] - outlet[1]) / 1000.0


def _flow_station_xy(
    attributes: dict[str, Any],
    *,
    target_crs: str,
) -> tuple[float, float] | None:
    x = _first_float(attributes, "flow_station_x", "hydro_station_x", "station_x")
    y = _first_float(attributes, "flow_station_y", "hydro_station_y", "station_y")
    if x is None or y is None:
        return None
    source_crs = _first_text(
        attributes,
        "flow_station_crs",
        "hydro_station_crs",
        "station_crs",
        "source_location_crs",
    )
    return _xy_in_target_crs(x, y, source_crs=source_crs, target_crs=target_crs)


def _looks_station_led(catchment: DelineatedCatchment, attributes: dict[str, Any]) -> bool:
    if catchment.outlet.source in {"station_outlets", "hubeau_hydrometrie"}:
        return True
    return any(
        _first_text(attributes, key) is not None
        for key in ("flow_station_id", "hydro_station_id", "station_id")
    )


def _xy_in_target_crs(
    x: float,
    y: float,
    *,
    source_crs: str | None,
    target_crs: str,
) -> tuple[float, float] | None:
    if source_crs is None or _same_crs(source_crs, target_crs):
        return x, y
    try:
        from pyproj import Transformer
    except ImportError:
        return None
    try:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        target_x, target_y = transformer.transform(x, y)
    except Exception:
        return None
    return float(target_x), float(target_y)


def _same_crs(left: str, right: str) -> bool:
    if left.strip().upper() == right.strip().upper():
        return True
    try:
        from pyproj import CRS

        return CRS.from_user_input(left) == CRS.from_user_input(right)
    except Exception:
        return False


def _first_float(attributes: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = attributes.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
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


def _decision_from_components(
    *,
    catchment: DelineatedCatchment,
    selection_principle: str,
    selected: bool,
    decision_stage: str,
    decision_reason: str,
    components: list[CriteriaComponent],
    rank_score: float | None,
) -> SelectionDecision:
    blocking_flags = [
        component.criterion_id
        for component in components
        if component.blocking or component.criterion_status == "failed"
    ]
    warning_flags = [
        component.criterion_id
        for component in components
        if component.criterion_status == "warning"
    ]
    return SelectionDecision(
        site_id=catchment.site_id,
        selection_principle=selection_principle,
        selected=selected,
        decision_stage=decision_stage,
        decision_reason=decision_reason,
        blocking_flags=blocking_flags,
        warning_flags=warning_flags,
        rank_score=rank_score,
        criteria_summary_json={
            component.criterion_id: component.criterion_status for component in components
        },
    )


__all__ = [
    "SelectionDecision",
    "SelectionResult",
    "select_delineated_catchments",
]
