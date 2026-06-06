from __future__ import annotations

import pytest
from shapely.geometry import box

from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    CriteriaConfig,
    SpatialSelectionConfig,
)
from hydromodpy.spatial.site_selection.evaluation.selection import select_delineated_catchments
from hydromodpy.spatial.site_selection.hydrology.delineation import DelineatedCatchment
from tests.unit.site_selection._geojson import write_point_geojson


def _catchment(
    site_id: str,
    area_km2: float,
    priority: float = 0.0,
    *,
    x: float = 0.0,
    y: float = 0.0,
) -> DelineatedCatchment:
    return DelineatedCatchment(
        site_id=site_id,
        outlet=CandidateOutlet(site_id, x, y, "EPSG:2154", "test", priority=priority),
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
    rejected_decision = next(
        decision for decision in result.decisions if decision.site_id == "too_small"
    )
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
def test_select_delineated_catchments_rejects_configured_station_influence():
    influenced = DelineatedCatchment(
        site_id="station_influenced",
        outlet=CandidateOutlet(
            "station_influenced",
            0.0,
            0.0,
            "EPSG:2154",
            "hubeau_hydrometrie",
            source_feature_id="J123456701",
            attributes={
                "flow_station_id": "J123456701",
                "influence_generale_site": "1",
            },
        ),
        area_km2=100.0,
    )

    result = select_delineated_catchments(
        [influenced, _catchment("ok", 100.0)],
        criteria=CriteriaConfig.model_validate(
            {
                "area": {"mode": "report_only"},
                "observations": {
                    "station_influence": {
                        "mode": "hard_reject",
                    },
                },
            }
        ),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="observation_led",
    )

    assert [catchment.site_id for catchment in result.selected] == ["ok"]
    rejected_decision = next(
        decision for decision in result.decisions if decision.site_id == "station_influenced"
    )
    assert rejected_decision.blocking_flags == ["station_influence"]


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
def test_select_delineated_catchments_uses_snapped_outlet_for_flow_station_distance(
    tmp_path,
):
    snap_path = tmp_path / "outlet_snap.geojson"
    write_point_geojson(snap_path, coordinates=[3000.0, 0.0])
    catchment = DelineatedCatchment(
        site_id="station_far_after_snap",
        outlet=CandidateOutlet(
            "station_far_after_snap",
            0.0,
            0.0,
            "EPSG:2154",
            "hubeau_hydrometrie",
            attributes={
                "flow_station_id": "J001001001",
                "flow_station_x": "0.0",
                "flow_station_y": "0.0",
                "flow_station_crs": "EPSG:2154",
                "flow_station_record_years": "20.0",
                "station_to_outlet_distance_km": "0.0",
                "station_inside_or_at_outlet": "true",
            },
        ),
        outlet_snap_shp=str(snap_path),
        area_km2=100.0,
    )

    result = select_delineated_catchments(
        [catchment],
        criteria=CriteriaConfig.model_validate(
            {
                "area": {"mode": "report_only"},
                "observations": {
                    "flow_station": {
                        "mode": "hard_reject",
                        "min_record_years": 5.0,
                        "max_station_to_outlet_distance_km": 1.0,
                    }
                },
            }
        ),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="observation_led",
    )

    assert result.selected == []
    assert [item.site_id for item in result.rejected] == ["station_far_after_snap"]
    component = next(
        item for item in result.criteria_components if item.criterion_id == "flow_station"
    )
    assert component.blocking is True
    assert component.evidence_json["station_to_outlet_distance_km"] == pytest.approx(3.0)
    assert "exceeds 1" in component.reason


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


@pytest.mark.fast
def test_select_delineated_catchments_respects_max_selected_sites():
    result = select_delineated_catchments(
        [
            _catchment("best", 100.0, priority=10.0),
            _catchment("next", 100.0, priority=5.0),
            _catchment("third", 100.0, priority=1.0),
        ],
        criteria=CriteriaConfig(area=AreaCriteriaConfig(mode="report_only")),
        spatial_selection=SpatialSelectionConfig(max_selected_sites=2),
        selection_principle="criteria_crossing",
    )

    assert [catchment.site_id for catchment in result.selected] == ["best", "next"]
    assert [catchment.site_id for catchment in result.rejected] == ["third"]
    target_decision = next(decision for decision in result.decisions if decision.site_id == "third")
    assert target_decision.blocking_flags == ["target_count"]
    assert target_decision.decision_reason == "target count 2 reached"


@pytest.mark.fast
def test_select_delineated_catchments_rejects_outlets_too_close_after_ranking():
    result = select_delineated_catchments(
        [
            _catchment("a", 100.0, priority=10.0, x=0.0),
            _catchment("b", 100.0, priority=5.0, x=500.0),
            _catchment("c", 100.0, priority=1.0, x=2000.0),
        ],
        criteria=CriteriaConfig(area=AreaCriteriaConfig(mode="report_only")),
        spatial_selection=SpatialSelectionConfig(min_outlet_distance_km=1.0),
        selection_principle="criteria_crossing",
    )

    assert [catchment.site_id for catchment in result.selected] == ["a", "c"]
    assert [catchment.site_id for catchment in result.rejected] == ["b"]
    spacing_decision = next(decision for decision in result.decisions if decision.site_id == "b")
    assert spacing_decision.blocking_flags == ["outlet_spacing"]
    assert "below 1.000 km" in spacing_decision.decision_reason


@pytest.mark.fast
def test_select_delineated_catchments_applies_grid_spatial_quota():
    result = select_delineated_catchments(
        [
            _catchment("a", 100.0, priority=10.0, x=100.0, y=100.0),
            _catchment("b", 100.0, priority=9.0, x=500.0, y=500.0),
            _catchment("c", 100.0, priority=8.0, x=1500.0, y=100.0),
        ],
        criteria=CriteriaConfig(area=AreaCriteriaConfig(mode="report_only")),
        spatial_selection=SpatialSelectionConfig(
            spatial_quota_mode="grid",
            spatial_quota_cell_size_km=1.0,
            spatial_quota_max_sites_per_cell=1,
        ),
        selection_principle="criteria_crossing",
    )

    assert [catchment.site_id for catchment in result.selected] == ["a", "c"]
    assert [catchment.site_id for catchment in result.rejected] == ["b"]
    quota_decision = next(decision for decision in result.decisions if decision.site_id == "b")
    assert quota_decision.blocking_flags == ["spatial_quota"]
    quota_component = next(
        component
        for component in result.criteria_components
        if component.site_id == "b" and component.criterion_id == "spatial_quota"
    )
    assert quota_component.evidence_json["cell_key"] == "grid:0:0"
