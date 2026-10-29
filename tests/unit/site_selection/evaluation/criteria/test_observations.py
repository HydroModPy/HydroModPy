import pytest

from hydromodpy.spatial.site_selection.config.criteria_config import ObservationsCriteriaConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.observations import (
    evaluate_flow_station_criterion,
    evaluate_piezometer_criterion,
    evaluate_station_influence_criterion,
)

pytestmark = pytest.mark.fast

STATION = {"flow_station_id": "J123456701"}
GENERAL, NO_INFLUENCE, UNKNOWN = (
    {**STATION, "influence_generale_site": v} for v in ("1", "0", "9")
)
RETENUE = {**STATION, "commentaire_station": "Station proche d'une retenue."}
LONG_RECORD = {"record_years": "n/a", "flow_station_record_years": 20.0}
TEN_YEARS = {"mode": "hard_reject", "min_record_years": 10.0}


def _evaluate(evaluate, attributes: dict, config: dict, status, reason, score):
    """Evaluate one criterion; only a failed criterion blocks."""
    component = evaluate(
        site_id="site_001", attributes=attributes, config=ObservationsCriteriaConfig.model_validate(config),
        selection_principle="observation_led", evaluation_order=2,
    )  # fmt: skip
    assert (component.criterion_status, component.blocking) == (status, status == "failed")
    assert reason in component.reason
    assert component.score_component == pytest.approx(score)
    return component


@pytest.mark.parametrize(("detail", "attributes", "status", "reason", "score"), [
    (TEN_YEARS, {"n_records": 365}, "failed", "years is below 10", None),
    (TEN_YEARS | {"max_station_to_outlet_distance_km": 1.0}, {}, "failed",
     "record length is missing; station-to-outlet distance is missing", None),
    ({"mode": "warning", "max_station_to_outlet_distance_km": 1.0},
     {"station_to_outlet_distance_km": 3.0}, "warning", "3 km exceeds 1", None),
    ({"mode": "hard_reject", "require_station_inside_or_at_outlet": True},
     {**LONG_RECORD, "station_inside_or_at_outlet": "maybe", "station_inside_basin": "non"},
     "failed", "not flagged inside or at the outlet", None),
    (TEN_YEARS, LONG_RECORD, "passed", "flow-station checks passed", None),
    ({"mode": "warning"}, {}, "missing", "flow-station checks passed", None),
    ({"mode": "report_only"}, LONG_RECORD, "reported", "without automatic decision", None),
    ({"mode": "report_only"}, {}, "missing", "evidence is missing", None),
    ({"mode": "stratify"}, {"n_records": 3652.5}, "stratified", "stratification", None),
    ({"mode": "stratify"}, {}, "missing", "evidence is missing", None),
    ({"mode": "score", "min_record_years": 10.0, "max_station_to_outlet_distance_km": 2.0},
     {"record_years": 5.0, "hydro_station_distance_km": 1.0}, "scored", "evidence scored", 0.5),
    ({"mode": "score", "min_record_years": 10.0}, {}, "missing", "missing for score mode", None),
])  # fmt: skip
def test_the_flow_station_criterion_follows_its_mode(detail, attributes, status, reason, score):
    config = {"flow_station": detail}
    component = _evaluate(
        evaluate_flow_station_criterion, attributes, config, status, reason, score
    )
    assert component.evidence_json["evidence_ref"] is None


@pytest.mark.parametrize(("detail", "attributes", "status", "reason", "score"), [
    ({"mode": "warning"}, GENERAL, "warning", "general hydrologic influence", None),
    ({"mode": "hard_reject"}, {**STATION, "flow_station_influence_generale_site": "oui"}, "failed",
     "general hydrologic influence", None),
    ({"mode": "warning"}, {**STATION, "influence_locale_station": "1"}, "warning",
     "local hydrologic influence", None),
    ({"mode": "warning", "warn_if_general_influence": False}, GENERAL, "reported",
     "station influence metadata reported", None),
    ({"mode": "hard_reject", "unknown_policy": "neutral"}, STATION, "missing", "metadata is missing", None),
    ({"mode": "warning"}, NO_INFLUENCE, "passed", "reports no known influence", None),
    ({"mode": "warning", "unknown_policy": "warning"}, STATION, "warning", "metadata is missing", None),
    ({"mode": "warning", "unknown_policy": "warning"}, UNKNOWN, "warning", "status is unknown", None),
    ({"mode": "warning"}, UNKNOWN, "reported", "status is unknown", None),
    ({"mode": "warning"}, RETENUE, "warning", "possible hydraulic influence", None),
    ({"mode": "warning"}, {**RETENUE, "influence_generale_site": "1"}, "warning",
     "station has general hydrologic influence metadata", None),
    ({"mode": "hard_reject"}, RETENUE, "warning", "possible hydraulic influence", None),
    ({"mode": "report_only"}, GENERAL, "reported", "without automatic decision", None),
    ({"mode": "report_only"}, STATION, "missing", "metadata is missing", None),
    ({"mode": "score"}, NO_INFLUENCE, "scored", "metadata scored", 1.0),
    ({"mode": "score"}, UNKNOWN, "scored", "metadata scored", 0.5),
    ({"mode": "score"}, GENERAL, "scored", "metadata scored", 0.0),
    ({"mode": "score"}, STATION, "missing", "missing for score mode", None),
    ({"mode": "stratify"}, GENERAL, "stratified", "stratification", None),
    ({"mode": "stratify"}, STATION, "missing", "metadata is missing", None),
])  # fmt: skip
def test_the_station_influence_criterion_follows_its_mode(
    detail, attributes, status, reason, score
):
    config = {"station_influence": detail}
    component = _evaluate(evaluate_station_influence_criterion, attributes, config, status, reason, score)  # fmt: skip
    assert component.evidence_json["evidence_ref"] == "flow_station:site_001:J123456701"
    if "commentaire_station" in attributes:  # a comment keyword is reported beside the status
        assert "retenue" in component.evidence_json["matched_keywords"]
        general = attributes.get("influence_generale_site") == "1"
        assert component.raw_value == ("general_influence" if general else "unknown")


@pytest.mark.parametrize(("config", "attributes", "status", "reason", "score"), [
    ({"piezometer_mode": "warning", "piezometer_max_distance_km": 2.0},
     {"nearest_piezometer_distance_km": 5.0}, "warning", "5 km exceeds 2", None),
    ({"piezometer_mode": "hard_reject", "piezometer_max_distance_km": 2.0}, {}, "failed",
     "piezometer evidence is missing; piezometer distance is missing", None),
    ({"piezometer_mode": "hard_reject", "piezometer_max_distance_km": 2.0},
     {"piezometer_distance_km": 1.0}, "passed", "piezometer checks passed", None),
    ({"piezometer_mode": "hard_reject"}, {"piezometer_count": 1}, "passed", "piezometer checks passed", None),
    ({"piezometer_mode": "score", "piezometer_max_distance_km": 2.0},
     {"nearest_piezometer_distance_km": 0.5}, "scored", "evidence scored", 0.75),
    ({"piezometer_mode": "score"}, {"nearby_piezometer_count": 3}, "scored", "evidence scored", 1.0),
    ({"piezometer_mode": "score", "piezometer_max_distance_km": 2.0}, {}, "missing",
     "missing for score mode", None),
    ({"piezometer_mode": "report_only"}, {"piezometer_inside_basin": "oui"}, "reported",
     "without automatic decision", None),
    ({"piezometer_mode": "report_only"}, {}, "missing", "evidence is missing", None),
    ({"piezometer_mode": "stratify"}, {"piezometers_in_basin": 2}, "stratified", "stratification", None),
    ({"piezometer_mode": "stratify"}, {"piezometer_count": 0}, "missing", "evidence is missing", None),
])  # fmt: skip
def test_the_piezometer_criterion_follows_its_mode(config, attributes, status, reason, score):
    component = _evaluate(evaluate_piezometer_criterion, attributes, config, status, reason, score)
    assert component.evidence_json["evidence_ref"] is None
