"""The README and the HTML say why a calibration search stopped, and the label holds.

A session states one of three stop states. Its README and its HTML report say
it in words, with the phases that froze the best of a budget-only search. The
README of the promoted run says it beside the session that promoted it. The
stop state does not enter the label: ``failed`` stays the label of a fiction
(a fatal validity, a solver that did not converge). A run promoted by a
budget-only search, whose session closes ``completed``, stays ``calibrated``,
and one promoted by a search stopped before its rule, whose session closes
``partial``, stays ``exploratory``, so the rules keep their version.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hydromodpy.reporting.calibration_report import _render_html
from hydromodpy.results.checks import BUDGET_RULE, FROZE_BUDGET_ONLY, CalibratedBy
from hydromodpy.results.readme import _checks_section, render_session_readme
from hydromodpy.results.session.descriptor import SessionDescriptor
from hydromodpy.results.session.phase import PhaseDescriptor
from hydromodpy.results.validity_rules import RULE_VERSION, label_for
from tests.unit.results._run_record_factory import make_checks


def _descriptor(**extra) -> SessionDescriptor:
    return SessionDescriptor(
        session_id="sess0001",
        case_id="J0014010-calage",
        config_hash="h",
        hydromodpy_version="2.0.0a5",
        method="random_search + grid",
        objective_name="nse_log",
        status="completed",
        started_at=datetime(2026, 10, 25, tzinfo=UTC),
        **extra,
    )


def test_the_session_readme_says_why_each_search_stopped() -> None:
    descriptor = _descriptor(
        stop_state="plan_exhausted",
        stopping_rule="every grid point",
        stop_note=f"phase coarse {FROZE_BUDGET_ONLY}",
    )
    phases = [
        PhaseDescriptor(
            phase_id="p1",
            name="coarse",
            index=0,
            status="completed",
            stop_state="budget_spent",
            stopping_rule=BUDGET_RULE,
            stop_note=FROZE_BUDGET_ONLY,
        ),
        PhaseDescriptor(
            phase_id="p2",
            name="storage",
            index=1,
            status="completed",
            stop_state="plan_exhausted",
            stopping_rule="every grid point",
        ),
    ]

    text = render_session_readme(descriptor, [], None, phases=phases)

    assert "- search stopped: exhausted its plan (every grid point solved), converged" in text
    assert f"- phase coarse {FROZE_BUDGET_ONLY}" in text
    assert (
        "| coarse | completed | 0 | {} | none | spent its budget, a budget-only search with "
        f"no rule of its own; {FROZE_BUDGET_ONLY} |"
    ) in text
    assert (
        "| storage | completed | 0 | {} | none | exhausted its plan (every grid point solved) |"
        in (text)
    )


def test_an_older_session_says_its_stop_was_not_recorded() -> None:
    text = render_session_readme(_descriptor(), [], None)

    assert "- search stopped: not recorded" in text


def test_the_run_readme_says_why_the_search_that_promoted_it_stopped() -> None:
    checks = make_checks(
        calibrated_by=CalibratedBy(
            session_id="sess0001",
            phase="storage",
            trial=7,
            session_status="completed",
            stop_state="budget_spent",
            stopping_rule=BUDGET_RULE,
        )
    )

    lines = _checks_section(checks)

    assert (
        "- its search spent its budget, a budget-only search with no rule of its own, not converged"
    ) in lines


def test_the_html_report_says_why_the_search_stopped() -> None:
    session = _descriptor(
        stop_state="budget_spent", stopping_rule="xatol", stop_note=None
    ).model_dump(mode="json", by_alias=True)

    page = _render_html(session, [], [])

    assert (
        "<tr><th>search stopped</th><td>spent its budget before its rule (xatol) was met, "
        "not converged</td></tr>"
    ) in page


def test_a_budget_only_search_promotes_a_calibrated_run_and_never_a_failed_one() -> None:
    def label(status: str) -> str:
        checks = make_checks(
            calibrated_by=CalibratedBy(
                session_id="sess0001",
                trial=7,
                session_status=status,
                stop_state="budget_spent",
                stopping_rule=BUDGET_RULE,
            ),
            score_window=None,
            n_samples=None,
        )
        return label_for(checks, hydromodpy_version="2.0.0a5", issues=()).label

    assert label("completed") == "calibrated"
    assert label("partial") == "exploratory"
    assert RULE_VERSION == "2"
