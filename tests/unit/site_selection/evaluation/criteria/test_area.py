import pytest

from hydromodpy.site_selection.config.criteria_config import AreaCriteriaConfig
from hydromodpy.site_selection.evaluation.criteria.area import evaluate_area_criterion

pytestmark = pytest.mark.fast

BOUNDS = {"hard_min_area_km2": 75.0, "hard_max_area_km2": 125.0}
RANGE = {"range_id": "medium", "label": "Bassins moyens", "min_area_km2": 50.0, "max_area_km2": 150.0}  # fmt: skip
SCORE = {"mode": "score", "preferred_area_km2": 100.0, "score_half_width_fraction": 0.5}


def _area(area_km2: float | None, config: dict):
    return evaluate_area_criterion(
        site_id="site_001", area_km2=area_km2, config=AreaCriteriaConfig.model_validate(config),
        selection_principle="criteria_crossing",
    )  # fmt: skip


@pytest.mark.parametrize(("area", "config", "status", "blocking", "reason"), [
    (60.0, {"mode": "hard_reject", **BOUNDS}, "failed", True, "below hard_min_area_km2 75"),
    (130.0, {"mode": "hard_reject", **BOUNDS}, "failed", True, "above hard_max_area_km2 125"),
    (100.0, {"mode": "hard_reject", **BOUNDS}, "passed", False, "inside configured hard"),
    (42.0, {"mode": "hard_reject", "ranges": [RANGE]}, "failed", True, "outside configured"),
    (100.0, {"mode": "hard_reject", "ranges": [RANGE]}, "passed", False, "inside configured"),
    (60.0, {"mode": "warning", **BOUNDS}, "warning", False, "below hard_min_area_km2"),
    (100.0, {"mode": "warning", **BOUNDS}, "passed", False, "does not trigger a warning"),
    (100.0, {"mode": "stratify"}, "stratified", False, "available for stratification"),
    (100.0, {"mode": "report_only"}, "reported", False, "without automatic decision"),
    (None, {"mode": "report_only"}, "missing", False, "area_km2 is missing"),
    (None, {"mode": "hard_reject", **BOUNDS}, "missing", True, "area_km2 is missing"),
])  # fmt: skip
def test_the_area_criterion_follows_its_mode(area, config, status, blocking, reason):
    component = _area(area, config)
    assert (component.criterion_status, component.blocking) == (status, blocking)
    assert reason in component.reason
    assert component.raw_value == area
    if "ranges" in config:  # an area range names itself in the threshold
        assert component.threshold == "Bassins moyens (50-150 km2)"
        assert component.evidence_json["ranges"][0]["min_area_km2"] == pytest.approx(50.0)


@pytest.mark.parametrize(("area", "score", "normalized"), [(100.0, 1.0, 0.0), (150.0, 0.0, 1.0)])
def test_the_area_score_falls_from_one_at_the_preferred_area_to_zero_at_half_width(area, score, normalized):  # fmt: skip
    component = _area(area, SCORE)
    assert component.criterion_status == "scored"
    assert component.score_component == pytest.approx(score)
    assert component.normalized_value == pytest.approx(normalized)
