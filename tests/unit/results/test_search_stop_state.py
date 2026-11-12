"""How a session says why its search stopped, in the run README, the report and the label.

A session states one of three stop states. The README and the HTML report say it in words.
The stop state does not enter the label: a run promoted by a budget-only search whose session
closes ``completed`` stays ``calibrated``, and one whose session closes ``partial`` stays
``exploratory``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hydromodpy.results.readme import _checks_section
from hydromodpy.results.record.checks import BUDGET_RULE, CalibratedBy
from hydromodpy.results.session.descriptor import write_session
from hydromodpy.results.session.summary import session_summary, summary_rows
from hydromodpy.results.session.view import Session
from hydromodpy.results.validity_rules import RULE_VERSION, label_for
from tests._helpers.run_records import make_checks
from tests._helpers.session_documents import session_descriptor


def budget_spent(session_status, **extra):
    return CalibratedBy(
        session_id="sess0001",
        trial=7,
        session_status=session_status,
        stop_state="budget_spent",
        stopping_rule=BUDGET_RULE,
        **extra,
    )


def test_the_run_readme_says_why_the_search_stopped():
    checks = make_checks(calibrated_by=budget_spent("completed", phase="storage"))

    lines = _checks_section(checks)

    assert (
        "- its search spent its budget, a budget-only search with no rule of its own, not converged"
    ) in lines


def test_the_html_report_says_why_the_search_stopped(tmp_path):
    directory = tmp_path / "sessions" / "J0014010-calage"
    directory.mkdir(parents=True)
    descriptor = session_descriptor(
        "J0014010-calage",
        session_id="sess0001",
        method="random_search + grid",
        cost_name="nse_log",
        status="completed",
        started_at=datetime(2026, 10, 25, tzinfo=UTC),
        stop_state="budget_spent",
        stopping_rule="xatol",
        stop_note=None,
    )
    write_session(directory, descriptor)

    summary = dict(summary_rows(session_summary(Session(directory))))

    assert summary["search stopped"] == (
        "spent its budget before its rule (xatol) was met, not converged"
    )


def test_a_budget_only_search_promotes_a_calibrated_run_and_never_a_failed_one():
    def label(status):
        checks = make_checks(
            calibrated_by=budget_spent(status, cost=0.25), score_window=None, n_samples=None
        )
        return label_for(
            checks, hydromodpy_version="2.0.0a5", issues=(), flow_regime="steady"
        ).label

    assert label("completed") == "calibrated"
    assert label("partial") == "exploratory"
    assert RULE_VERSION == "3"
