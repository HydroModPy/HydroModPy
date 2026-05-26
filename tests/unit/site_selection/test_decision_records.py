from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.decisions import (
    DecisionRecord,
    aggregate_site_selection_decisions,
    decision_records_from_selection_result,
)
from hydromodpy.spatial.site_selection.evaluation.criteria import CriteriaComponent
from hydromodpy.spatial.site_selection.evaluation.selection import (
    SelectionDecision,
    SelectionResult,
)


def _record(decision: str, catchment_id: str = "site_001") -> DecisionRecord:
    return DecisionRecord(
        run_id="run_v1",
        catchment_id=catchment_id,
        criterion_family="test",
        criterion_id=decision.lower(),
        decision=decision,  # type: ignore[arg-type]
        message=f"{decision} reason",
    )


@pytest.mark.fast
def test_aggregate_site_selection_decisions_prioritizes_reject():
    summaries = aggregate_site_selection_decisions(
        [_record("ACCEPT"), _record("WARNING"), _record("REJECT")]
    )

    assert summaries[0].global_decision == "REJECT"
    assert summaries[0].n_accept == 1
    assert summaries[0].n_warning == 1
    assert summaries[0].n_reject == 1
    assert summaries[0].reject_reasons == ["reject: REJECT reason"]


@pytest.mark.fast
@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ([_record("WARNING")], "ACCEPT_WITH_WARNINGS"),
        ([_record("ACCEPT")], "ACCEPT"),
        ([_record("NEUTRAL")], "NEUTRAL"),
    ],
)
def test_aggregate_site_selection_decisions_handles_non_reject_states(
    records,
    expected,
):
    summaries = aggregate_site_selection_decisions(records)

    assert summaries[0].global_decision == expected


@pytest.mark.fast
def test_decision_records_from_selection_result_adapts_components_and_final_decision():
    result = SelectionResult(
        selected=[],
        rejected=[],
        decisions=[
            SelectionDecision(
                site_id="site_001",
                selection_principle="criteria_crossing",
                selected=False,
                decision_stage="selection",
                decision_reason="target_count_reached",
                blocking_flags=["target_count_reached"],
            )
        ],
        criteria_components=[
            CriteriaComponent(
                site_id="site_001",
                selection_principle="criteria_crossing",
                criterion_id="area",
                criterion_family="geometry",
                criterion_mode="hard_reject",
                evaluation_stage="criteria",
                evaluation_order=0,
                criterion_status="passed",
                raw_value=101.5,
                threshold="80-120 km2",
                reason="area is inside configured hard bounds",
            ),
            CriteriaComponent(
                site_id="site_001",
                selection_principle="criteria_crossing",
                criterion_id="influence",
                criterion_family="anthropic_influence",
                criterion_mode="warning",
                evaluation_stage="criteria",
                evaluation_order=1,
                criterion_status="warning",
                raw_value=True,
                reason="secondary influence detected",
                evidence_json={"source_name": "custom_influence"},
            ),
        ],
    )

    records = decision_records_from_selection_result(result, run_id="run_v1")
    by_id = {(record.criterion_family, record.criterion_id): record for record in records}

    assert by_id[("geometry", "area")].decision == "ACCEPT"
    assert by_id[("anthropic_influence", "influence")].decision == "WARNING"
    assert by_id[("anthropic_influence", "influence")].source_name == "custom_influence"
    assert by_id[("selection", "final_selection")].decision == "REJECT"

    summary = aggregate_site_selection_decisions(records)[0]
    assert summary.global_decision == "REJECT"
    assert "final_selection: target_count_reached" in summary.reject_reasons
