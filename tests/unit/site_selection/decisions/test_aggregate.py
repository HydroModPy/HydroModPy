import pytest

from hydromodpy.spatial.site_selection.decisions.aggregate import (
    aggregate_site_selection_decisions,
)
from hydromodpy.spatial.site_selection.decisions.models import DecisionRecord

pytestmark = pytest.mark.fast


def _record(decision: str, message: str | None = "reason", ref: str | None = None):
    return DecisionRecord(
        run_id="run_v1", catchment_id="site_001", criterion_family="test", criterion_id=decision.lower(),
        decision=decision, message=message, evidence_ref=ref,  # type: ignore[arg-type]
    )  # fmt: skip


@pytest.mark.parametrize(("decisions", "expected"), [
    (["ACCEPT", "WARNING", "REJECT"], "REJECT"),
    (["ACCEPT", "WARNING"], "ACCEPT_WITH_WARNINGS"),
    (["NEUTRAL", "ACCEPT"], "ACCEPT"),
    (["NEUTRAL"], "NEUTRAL"),
])  # fmt: skip
def test_the_worst_record_sets_the_global_decision(decisions, expected):
    (summary,) = aggregate_site_selection_decisions([_record(item) for item in decisions])
    assert summary.global_decision == expected
    counts = [summary.n_accept, summary.n_warning, summary.n_reject, summary.n_neutral]
    assert counts == [decisions.count(item) for item in ("ACCEPT", "WARNING", "REJECT", "NEUTRAL")]


def test_the_summary_lists_each_reason_and_reference_once():
    records = [
        _record("REJECT", "too small", "area:1"),
        _record("REJECT", "too small", "area:1"),
        _record("REJECT", None, "area:2"),
        _record("WARNING", "far station"),
    ]

    (summary,) = aggregate_site_selection_decisions(records)

    record = summary.to_record()
    assert record["reject_reasons"] == ["reject: too small", "reject"]
    assert record["warning_reasons"] == ["warning: far station"]
    assert record["evidence_refs"] == ["area:1", "area:2"]
    assert record["n_reject"] == 3
