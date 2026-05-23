from __future__ import annotations

import pytest
from shapely.geometry import box

from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    CriteriaConfig,
    SpatialSelectionConfig,
)
from hydromodpy.spatial.site_selection.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.selection import select_delineated_catchments


def _catchment(site_id: str, area_km2: float, priority: float = 0.0) -> DelineatedCatchment:
    return DelineatedCatchment(
        site_id=site_id,
        outlet=CandidateOutlet(site_id, 0.0, 0.0, "EPSG:2154", "test", priority=priority),
        area_km2=area_km2,
        watershed_shp=f"{site_id}.shp",
    )


@pytest.mark.fast
def test_select_delineated_catchments_rejects_area_hard_failures():
    result = select_delineated_catchments(
        [_catchment("too_small", 50.0), _catchment("ok", 100.0)],
        criteria=CriteriaConfig(
            area=AreaCriteriaConfig(
                mode="hard_reject",
                hard_min_area_km2=75.0,
                hard_max_area_km2=125.0,
            )
        ),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="criteria_crossing",
    )

    assert [catchment.site_id for catchment in result.selected] == ["ok"]
    assert [catchment.site_id for catchment in result.rejected] == ["too_small"]
    rejected_decision = next(decision for decision in result.decisions if decision.site_id == "too_small")
    assert rejected_decision.blocking_flags == ["area"]


@pytest.mark.fast
def test_select_delineated_catchments_rejects_configured_major_influence():
    influenced = DelineatedCatchment(
        site_id="influenced",
        outlet=CandidateOutlet(
            "influenced",
            0.0,
            0.0,
            "EPSG:2154",
            "test",
            attributes={"major_dam_upstream": "true"},
        ),
        area_km2=100.0,
    )

    result = select_delineated_catchments(
        [influenced, _catchment("ok", 100.0)],
        criteria=CriteriaConfig.model_validate(
            {
                "area": {"mode": "report_only"},
                "influence": {
                    "mode": "hard_reject",
                    "reject_major_dam_upstream": True,
                },
            }
        ),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="observation_led",
    )

    assert [catchment.site_id for catchment in result.selected] == ["ok"]
    rejected_decision = next(
        decision for decision in result.decisions if decision.site_id == "influenced"
    )
    assert rejected_decision.blocking_flags == ["influence"]


@pytest.mark.fast
def test_select_delineated_catchments_keeps_piezometer_warning_auditable():
    catchment = DelineatedCatchment(
        site_id="far_piezometer",
        outlet=CandidateOutlet(
            "far_piezometer",
            0.0,
            0.0,
            "EPSG:2154",
            "test",
            attributes={"nearest_piezometer_distance_km": 5.0},
        ),
        area_km2=100.0,
    )

    result = select_delineated_catchments(
        [catchment],
        criteria=CriteriaConfig.model_validate(
            {
                "area": {"mode": "report_only"},
                "observations": {
                    "piezometer_mode": "warning",
                    "piezometer_max_distance_km": 2.0,
                },
            }
        ),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="criteria_crossing",
    )

    assert [item.site_id for item in result.selected] == ["far_piezometer"]
    decision = result.decisions[0]
    assert decision.warning_flags == ["piezometer"]
    component = next(
        item for item in result.criteria_components if item.criterion_id == "piezometer"
    )
    assert component.criterion_status == "warning"


@pytest.mark.fast
def test_select_delineated_catchments_rejects_overlapping_lower_ranked_basin():
    result = select_delineated_catchments(
        [_catchment("a", 100.0, priority=10.0), _catchment("b", 100.0, priority=1.0)],
        criteria=CriteriaConfig(area=AreaCriteriaConfig(mode="report_only")),
        spatial_selection=SpatialSelectionConfig(
            max_pairwise_basin_overlap_fraction=0.05,
            overlap_mode="hard_reject",
        ),
        selection_principle="criteria_crossing",
        basin_geometries={
            "a": box(0.0, 0.0, 10.0, 10.0),
            "b": box(5.0, 0.0, 15.0, 10.0),
        },
    )

    assert [catchment.site_id for catchment in result.selected] == ["a"]
    assert [catchment.site_id for catchment in result.rejected] == ["b"]
    overlap_decision = next(decision for decision in result.decisions if decision.site_id == "b")
    assert overlap_decision.blocking_flags == ["basin_overlap"]


@pytest.mark.fast
def test_select_delineated_catchments_keeps_overlap_when_mode_warning():
    result = select_delineated_catchments(
        [_catchment("a", 100.0, priority=10.0), _catchment("b", 100.0, priority=1.0)],
        criteria=CriteriaConfig(area=AreaCriteriaConfig(mode="report_only")),
        spatial_selection=SpatialSelectionConfig(
            max_pairwise_basin_overlap_fraction=0.05,
            overlap_mode="warning",
        ),
        selection_principle="observation_led",
        basin_geometries={
            "a": box(0.0, 0.0, 10.0, 10.0),
            "b": box(5.0, 0.0, 15.0, 10.0),
        },
    )

    assert [catchment.site_id for catchment in result.selected] == ["a", "b"]
    warning_decision = next(decision for decision in result.decisions if decision.site_id == "b")
    assert warning_decision.warning_flags == ["basin_overlap"]


@pytest.mark.fast
def test_select_delineated_catchments_carries_delineation_failures():
    failed = DelineatedCatchment(
        site_id="failed",
        outlet=CandidateOutlet("failed", 0.0, 0.0, "EPSG:2154", "test"),
        status="rejected_delineation_failed",
        failure_reason="snap failed",
    )

    result = select_delineated_catchments(
        [failed],
        criteria=CriteriaConfig(area=AreaCriteriaConfig(mode="report_only")),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="criteria_crossing",
    )

    assert result.selected == []
    assert result.rejected == [failed]
    assert result.decisions[0].decision_stage == "delineation"
