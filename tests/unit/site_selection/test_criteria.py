from __future__ import annotations

import json

import numpy as np
import pytest

from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    GeologyCriteriaConfig,
    InfluenceCriteriaConfig,
    ObservationsCriteriaConfig,
)
from hydromodpy.spatial.site_selection.evaluation.criteria import (
    evaluate_area_criterion,
    evaluate_flow_station_criterion,
    evaluate_geology_criterion,
    evaluate_influence_criterion,
    evaluate_piezometer_criterion,
    evaluate_station_influence_criterion,
)


@pytest.mark.fast
def test_evaluate_area_hard_reject_blocks_outside_bounds():
    component = evaluate_area_criterion(
        site_id="site_001",
        area_km2=60.0,
        config=AreaCriteriaConfig(
            mode="hard_reject",
            hard_min_area_km2=75.0,
            hard_max_area_km2=125.0,
        ),
        selection_principle="criteria_crossing",
    )

    assert component.criterion_status == "failed"
    assert component.blocking is True
    assert "below" in component.reason


@pytest.mark.fast
def test_evaluate_area_hard_reject_passes_inside_bounds():
    component = evaluate_area_criterion(
        site_id="site_001",
        area_km2=100.0,
        config=AreaCriteriaConfig(
            mode="hard_reject",
            hard_min_area_km2=75.0,
            hard_max_area_km2=125.0,
        ),
        selection_principle="criteria_crossing",
    )

    assert component.criterion_status == "passed"
    assert component.blocking is False


@pytest.mark.fast
def test_evaluate_area_range_hard_reject_uses_readable_min_max_ranges():
    component = evaluate_area_criterion(
        site_id="site_001",
        area_km2=42.0,
        config=AreaCriteriaConfig.model_validate(
            {
                "mode": "hard_reject",
                "ranges": [
                    {
                        "range_id": "medium",
                        "label": "Bassins moyens",
                        "min_area_km2": 50.0,
                        "max_area_km2": 150.0,
                    }
                ],
            }
        ),
        selection_principle="criteria_crossing",
    )

    assert component.criterion_status == "failed"
    assert component.blocking is True
    assert "outside configured area ranges" in component.reason
    assert component.threshold == "Bassins moyens (50-150 km2)"
    assert component.evidence_json["ranges"][0]["min_area_km2"] == pytest.approx(50.0)


@pytest.mark.fast
def test_evaluate_area_score_is_one_at_preferred_area_and_zero_at_half_width():
    cfg = AreaCriteriaConfig(
        mode="score",
        preferred_area_km2=100.0,
        score_half_width_fraction=0.5,
    )

    best = evaluate_area_criterion(
        site_id="site_001",
        area_km2=100.0,
        config=cfg,
        selection_principle="criteria_crossing",
    )
    edge = evaluate_area_criterion(
        site_id="site_002",
        area_km2=150.0,
        config=cfg,
        selection_principle="criteria_crossing",
    )

    assert best.score_component == pytest.approx(1.0)
    assert edge.score_component == pytest.approx(0.0)
    assert edge.normalized_value == pytest.approx(1.0)


@pytest.mark.fast
def test_evaluate_area_report_only_never_blocks_missing_area():
    component = evaluate_area_criterion(
        site_id="site_001",
        area_km2=None,
        config=AreaCriteriaConfig(mode="report_only"),
        selection_principle="criteria_crossing",
    )

    assert component.criterion_status == "missing"
    assert component.blocking is False


@pytest.mark.fast
def test_evaluate_flow_station_hard_reject_blocks_short_records():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "flow_station": {
                "mode": "hard_reject",
                "min_record_years": 10.0,
            }
        }
    )

    component = evaluate_flow_station_criterion(
        site_id="site_001",
        attributes={"n_records": 365},
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=1,
    )

    assert component.criterion_status == "failed"
    assert component.blocking is True
    assert "below" in component.reason
    assert component.evidence_json["evidence_ref"] is None


@pytest.mark.fast
def test_evaluate_influence_hard_reject_blocks_major_dam_flag():
    component = evaluate_influence_criterion(
        site_id="site_001",
        attributes={"major_dam_upstream": "true"},
        config=InfluenceCriteriaConfig(
            mode="hard_reject",
            reject_major_dam_upstream=True,
        ),
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "failed"
    assert component.blocking is True
    assert component.criterion_id == "influence"


@pytest.mark.fast
def test_evaluate_station_influence_warning_flags_hubeau_general_influence():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "warning",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={
            "flow_station_id": "J123456701",
            "influence_generale_site": "1",
        },
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "warning"
    assert component.blocking is False
    assert component.raw_value == "general_influence"
    assert "general hydrologic influence" in component.reason
    assert component.evidence_json["evidence_ref"] == "flow_station:site_001:J123456701"


@pytest.mark.fast
def test_evaluate_station_influence_keeps_numpy_metadata_json_serializable():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "warning",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={
            "flow_station_id": "J123456701",
            "flow_station_influence_locale_station": np.int64(1),
        },
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "warning"
    assert component.evidence_json["station_influence_raw_fields"] == {
        "flow_station_influence_locale_station": 1
    }
    json.dumps(component.to_record())


@pytest.mark.fast
def test_evaluate_station_influence_hard_reject_can_block_general_influence():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "hard_reject",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={
            "flow_station_id": "J123456701",
            "flow_station_influence_generale_site": "oui",
        },
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "failed"
    assert component.blocking is True


@pytest.mark.fast
def test_evaluate_station_influence_hard_reject_keeps_missing_metadata():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "hard_reject",
                "unknown_policy": "neutral",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={"flow_station_id": "J123456701"},
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "missing"
    assert component.blocking is False


@pytest.mark.fast
def test_evaluate_station_influence_passes_explicit_no_known_influence():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "warning",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={
            "flow_station_id": "J123456701",
            "influence_generale_site": "0",
        },
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "passed"
    assert component.blocking is False


@pytest.mark.fast
def test_evaluate_station_influence_unknown_policy_can_warn():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "warning",
                "unknown_policy": "warning",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={"flow_station_id": "J123456701"},
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "warning"
    assert "missing" in component.reason


@pytest.mark.fast
def test_evaluate_station_influence_comment_keyword_warns():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "warning",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={
            "flow_station_id": "J123456701",
            "commentaire_station": "Station proche d'une retenue.",
        },
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "warning"
    assert component.blocking is False
    assert component.raw_value == "unknown"
    assert "retenue" in component.evidence_json["matched_keywords"]


@pytest.mark.fast
def test_evaluate_station_influence_hard_reject_does_not_block_comment_keyword():
    cfg = ObservationsCriteriaConfig.model_validate(
        {
            "station_influence": {
                "mode": "hard_reject",
            }
        }
    )

    component = evaluate_station_influence_criterion(
        site_id="site_001",
        attributes={
            "flow_station_id": "J123456701",
            "commentaire_station": "Station proche d'une retenue.",
        },
        config=cfg,
        selection_principle="observation_led",
        evaluation_order=2,
    )

    assert component.criterion_status == "warning"
    assert component.blocking is False
    assert "possible hydraulic influence" in component.reason


@pytest.mark.fast
def test_evaluate_geology_report_only_keeps_available_class():
    component = evaluate_geology_criterion(
        site_id="site_001",
        attributes={"dominant_geology": "socle cristallin"},
        config=GeologyCriteriaConfig(mode="report_only"),
        selection_principle="criteria_crossing",
        evaluation_order=3,
    )

    assert component.criterion_status == "reported"
    assert component.raw_value == "socle cristallin"
    assert component.blocking is False


@pytest.mark.fast
def test_evaluate_piezometer_warning_flags_far_observation():
    cfg = ObservationsCriteriaConfig(
        piezometer_mode="warning",
        piezometer_max_distance_km=2.0,
    )

    component = evaluate_piezometer_criterion(
        site_id="site_001",
        attributes={"nearest_piezometer_distance_km": 5.0},
        config=cfg,
        selection_principle="criteria_crossing",
        evaluation_order=2,
    )

    assert component.criterion_status == "warning"
    assert component.blocking is False
    assert "exceeds" in component.reason
    assert component.evidence_json["evidence_ref"] is None


@pytest.mark.fast
def test_evaluate_piezometer_score_rewards_close_observation():
    cfg = ObservationsCriteriaConfig(
        piezometer_mode="score",
        piezometer_max_distance_km=2.0,
    )

    component = evaluate_piezometer_criterion(
        site_id="site_001",
        attributes={"nearest_piezometer_distance_km": 0.5},
        config=cfg,
        selection_principle="criteria_crossing",
        evaluation_order=2,
    )

    assert component.criterion_status == "scored"
    assert component.score_component == pytest.approx(0.75)
