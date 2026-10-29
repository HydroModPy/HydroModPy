import pytest

from hydromodpy.spatial.site_selection.config.criteria_config import GeologyCriteriaConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.geology import (
    evaluate_geology_criterion,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(("mode", "attributes", "status", "score"), [
    ("report_only", {"dominant_geology": "socle cristallin"}, "reported", None),
    ("report_only", {}, "missing", None),
    ("score", {"lithology": "schist"}, "scored", 1.0),
    ("score", {}, "missing", None),
    ("stratify", {"geology_class": "granite"}, "stratified", None),
    ("stratify", {"geology_class": "  "}, "missing", None),
    ("warning", {"brgm_code": "g1"}, "reported", None),
    ("hard_reject", {}, "missing", None),
])  # fmt: skip
def test_the_geology_criterion_follows_its_mode_and_never_blocks(mode, attributes, status, score):
    component = evaluate_geology_criterion(
        site_id="site_001",
        attributes={**attributes, "geology_source": "BRGM"},
        config=GeologyCriteriaConfig(mode=mode),
        selection_principle="criteria_crossing",
        evaluation_order=3,
    )

    assert component.criterion_status == status
    assert component.raw_value == (next(iter(attributes.values()), "").strip() or None)
    assert component.score_component == score
    assert component.weight == (None if score is None else 1.0)
    assert component.blocking is False
    expected_ref = f"geology:site_001:BRGM:{component.raw_value}" if component.raw_value else None
    assert component.evidence_json["evidence_ref"] == expected_ref
