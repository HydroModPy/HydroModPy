"""The three observation criteria: flow station, station influence and piezometer."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.config.criteria_config import ObservationsCriteriaConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.observations import (
    evaluate_flow_station_criterion,
    evaluate_piezometer_criterion,
    evaluate_station_influence_criterion,
)

pytestmark = pytest.mark.fast

STATION = {"flow_station_id": "J123456701"}
RETENUE = {**STATION, "commentaire_station": "Station proche d'une retenue."}
LONG_RECORD = {"record_years": "n/a", "flow_station_record_years": 20.0}


def _evaluate(evaluate, attributes: dict, config: dict):
    return evaluate(
        site_id="site_001",
        attributes=attributes,
        config=ObservationsCriteriaConfig.model_validate(config),
        selection_principle="observation_led",
        evaluation_order=2,
    )


def _assert(component, status, blocking, reason, score):
    assert (component.criterion_status, component.blocking) == (status, blocking)
    assert reason in component.reason
    assert component.score_component == pytest.approx(score)


@pytest.mark.parametrize(
    ("detail", "attributes", "status", "blocking", "reason", "score"),
    [
        ({"mode": "hard_reject", "min_record_years": 10.0}, {"n_records": 365}, "failed", True,
         "years is below 10", None),
        ({"mode": "hard_reject", "min_record_years": 10.0, "max_station_to_outlet_distance_km": 1.0},
         {}, "failed", True, "record length is missing; station-to-outlet distance is missing",
         None),
        ({"mode": "warning", "max_station_to_outlet_distance_km": 1.0},
         {"station_to_outlet_distance_km": 3.0}, "warning", False, "3 km exceeds 1", None),
        ({"mode": "hard_reject", "require_station_inside_or_at_outlet": True},
         {**LONG_RECORD, "station_inside_or_at_outlet": "maybe", "station_inside_basin": "non"},
         "failed", True, "not flagged inside or at the outlet", None),
        ({"mode": "hard_reject", "min_record_years": 10.0}, LONG_RECORD, "passed", False,
         "flow-station checks passed", None),
        ({"mode": "warning"}, {}, "missing", False, "flow-station checks passed", None),
        ({"mode": "report_only"}, LONG_RECORD, "reported", False, "without automatic decision",
         None),
        ({"mode": "report_only"}, {}, "missing", False, "evidence is missing", None),
        ({"mode": "stratify"}, {"n_records": 3652.5}, "stratified", False, "stratification", None),
        ({"mode": "stratify"}, {}, "missing", False, "evidence is missing", None),
        ({"mode": "score", "min_record_years": 10.0, "max_station_to_outlet_distance_km": 2.0},
         {"record_years": 5.0, "hydro_station_distance_km": 1.0}, "scored", False,
         "evidence scored", 0.5),
        ({"mode": "score", "min_record_years": 10.0}, {}, "missing", False,
         "missing for score mode", None),
    ],
)  # fmt: skip
def test_the_flow_station_criterion_follows_its_mode(
    detail, attributes, status, blocking, reason, score
):
    component = _evaluate(evaluate_flow_station_criterion, attributes, {"flow_station": detail})

    _assert(component, status, blocking, reason, score)
    assert component.evidence_json["evidence_ref"] is None


@pytest.mark.parametrize(
    ("detail", "attributes", "status", "blocking", "reason", "score"),
    [
        ({"mode": "warning"}, {**STATION, "influence_generale_site": "1"}, "warning", False,
         "general hydrologic influence", None),
        ({"mode": "hard_reject"}, {**STATION, "flow_station_influence_generale_site": "oui"},
         "failed", True, "general hydrologic influence", None),
        ({"mode": "warning"}, {**STATION, "influence_locale_station": "1"}, "warning", False,
         "local hydrologic influence", None),
        ({"mode": "warning", "warn_if_general_influence": False},
         {**STATION, "influence_generale_site": "1"}, "reported", False,
         "station influence metadata reported", None),
        ({"mode": "hard_reject", "unknown_policy": "neutral"}, STATION, "missing", False,
         "metadata is missing", None),
        ({"mode": "warning"}, {**STATION, "influence_generale_site": "0"}, "passed", False,
         "reports no known influence", None),
        ({"mode": "warning", "unknown_policy": "warning"}, STATION, "warning", False,
         "metadata is missing", None),
        ({"mode": "warning", "unknown_policy": "warning"},
         {**STATION, "influence_generale_site": "9"}, "warning", False, "status is unknown", None),
        ({"mode": "warning"}, {**STATION, "influence_generale_site": "9"}, "reported", False,
         "status is unknown", None),
        ({"mode": "warning"}, RETENUE, "warning", False, "possible hydraulic influence", None),
        ({"mode": "warning"}, {**RETENUE, "influence_generale_site": "1"}, "warning", False,
         "station has general hydrologic influence metadata", None),
        ({"mode": "hard_reject"}, RETENUE, "warning", False, "possible hydraulic influence", None),
        ({"mode": "report_only"}, {**STATION, "influence_generale_site": "1"}, "reported", False,
         "without automatic decision", None),
        ({"mode": "report_only"}, STATION, "missing", False, "metadata is missing", None),
        ({"mode": "score"}, {**STATION, "influence_generale_site": "0"}, "scored", False,
         "metadata scored", 1.0),
        ({"mode": "score"}, {**STATION, "influence_generale_site": "9"}, "scored", False,
         "metadata scored", 0.5),
        ({"mode": "score"}, {**STATION, "influence_generale_site": "1"}, "scored", False,
         "metadata scored", 0.0),
        ({"mode": "score"}, STATION, "missing", False, "missing for score mode", None),
        ({"mode": "stratify"}, {**STATION, "influence_generale_site": "1"}, "stratified", False,
         "stratification", None),
        ({"mode": "stratify"}, STATION, "missing", False, "metadata is missing", None),
    ],
)  # fmt: skip
def test_the_station_influence_criterion_follows_its_mode(
    detail, attributes, status, blocking, reason, score
):
    component = _evaluate(
        evaluate_station_influence_criterion, attributes, {"station_influence": detail}
    )

    _assert(component, status, blocking, reason, score)
    assert component.evidence_json["evidence_ref"] == "flow_station:site_001:J123456701"


@pytest.mark.parametrize(
    ("attributes", "raw"),
    [(RETENUE, "unknown"), ({**RETENUE, "influence_generale_site": "1"}, "general_influence")],
)
def test_a_comment_keyword_is_reported_beside_the_influence_status(attributes, raw):
    component = _evaluate(
        evaluate_station_influence_criterion, attributes, {"station_influence": {"mode": "warning"}}
    )

    assert component.raw_value == raw
    assert "retenue" in component.evidence_json["matched_keywords"]


@pytest.mark.parametrize(
    ("config", "attributes", "status", "blocking", "reason", "score"),
    [
        ({"piezometer_mode": "warning", "piezometer_max_distance_km": 2.0},
         {"nearest_piezometer_distance_km": 5.0}, "warning", False, "5 km exceeds 2", None),
        ({"piezometer_mode": "hard_reject", "piezometer_max_distance_km": 2.0}, {}, "failed", True,
         "piezometer evidence is missing; piezometer distance is missing", None),
        ({"piezometer_mode": "hard_reject", "piezometer_max_distance_km": 2.0},
         {"piezometer_distance_km": 1.0}, "passed", False, "piezometer checks passed", None),
        ({"piezometer_mode": "hard_reject"}, {"piezometer_count": 1}, "passed", False,
         "piezometer checks passed", None),
        ({"piezometer_mode": "score", "piezometer_max_distance_km": 2.0},
         {"nearest_piezometer_distance_km": 0.5}, "scored", False, "evidence scored", 0.75),
        ({"piezometer_mode": "score"}, {"nearby_piezometer_count": 3}, "scored", False,
         "evidence scored", 1.0),
        ({"piezometer_mode": "score", "piezometer_max_distance_km": 2.0}, {}, "missing", False,
         "missing for score mode", None),
        ({"piezometer_mode": "report_only"}, {"piezometer_inside_basin": "oui"}, "reported", False,
         "without automatic decision", None),
        ({"piezometer_mode": "report_only"}, {}, "missing", False, "evidence is missing", None),
        ({"piezometer_mode": "stratify"}, {"piezometers_in_basin": 2}, "stratified", False,
         "stratification", None),
        ({"piezometer_mode": "stratify"}, {"piezometer_count": 0}, "missing", False,
         "evidence is missing", None),
    ],
)  # fmt: skip
def test_the_piezometer_criterion_follows_its_mode(
    config, attributes, status, blocking, reason, score
):
    component = _evaluate(evaluate_piezometer_criterion, attributes, config)

    _assert(component, status, blocking, reason, score)
    assert component.evidence_json["evidence_ref"] is None
