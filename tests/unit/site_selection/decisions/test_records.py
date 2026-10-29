import pytest

from hydromodpy.spatial.site_selection.decisions.aggregate import (
    aggregate_site_selection_decisions,
)
from hydromodpy.spatial.site_selection.decisions.records import (
    decision_records_from_selection_result,
)
from hydromodpy.spatial.site_selection.evaluation.criteria.common import CriteriaComponent
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionDecision
from tests._helpers.site_selection_cases import make_selection

pytestmark = pytest.mark.fast


def _component(criterion_id: str, status: str, order: int, **fields) -> CriteriaComponent:
    return CriteriaComponent(
        site_id="site_001", selection_principle="criteria_crossing", criterion_id=criterion_id,
        criterion_family=fields.pop("family", "geometry"), criterion_mode="hard_reject",
        evaluation_stage="criteria", evaluation_order=order, criterion_status=status, **fields,
    )  # fmt: skip


RESULT = make_selection(
    decisions=[
        SelectionDecision(
            site_id="site_001", selection_principle="criteria_crossing", selected=False,
            decision_stage="selection", decision_reason="target_count_reached",
            blocking_flags=["target_count_reached"],
        )
    ],
    components=[
        _component("area", "passed", 0, raw_value=101.5, threshold="80-120 km2", reason="inside"),
        _component(
            "influence", "warning", 1, family="anthropic_influence", raw_value=True,
            evidence_json={"source_name": " ", "provider_source": "custom_influence"},
        ),
        _component("quota", "failed", 2, raw_value=[1, 2], evidence_json={"evidence_id": "q:1"}),
        _component("geology", "reported", 3, raw_value=None),
    ],
)  # fmt: skip


def test_each_component_and_the_optional_final_decision_become_one_record():
    records = decision_records_from_selection_result(RESULT, run_id="run_v1")

    by_id = {record.criterion_id: record for record in records}
    assert {key: record.decision for key, record in by_id.items()} == {
        "area": "ACCEPT", "influence": "WARNING", "quota": "REJECT", "geology": "NEUTRAL",
        "final_selection": "REJECT",
    }  # fmt: skip
    assert [record.criterion_id for record in records][-1] == "final_selection"
    assert by_id["influence"].source_name == "custom_influence"
    assert (by_id["quota"].metric_value, by_id["quota"].evidence_ref) == ("[1, 2]", "q:1")
    assert by_id["geology"].metric_value is None
    summary = aggregate_site_selection_decisions(records)[0]
    assert summary.global_decision == "REJECT"
    assert "final_selection: target_count_reached" in summary.reject_reasons
    without_final = decision_records_from_selection_result(
        RESULT, run_id="run_v1", include_final_selection=False
    )
    assert "final_selection" not in {record.criterion_id for record in without_final}
