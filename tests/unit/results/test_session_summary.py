"""The summary of a session: one writer of the rows the page and ``hmp show`` print."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hydromodpy.results.session.journal import BOUND_TOLERANCE, append_trial, on_bound
from hydromodpy.results.session.summary import SessionSummary, summary_rows
from hydromodpy.results.session.view import Session
from tests._helpers.sealed_runs import make_project, write_session_dir
from tests._helpers.session_documents import trial_line

pytestmark = pytest.mark.fast

BOUNDED = {"value": 1e-7, "bounds": (1e-7, 1e-4)}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"value": 1e-7, "bounds": (1e-7, 1e-4)}, True),
        ({"value": 1e-4, "bounds": (1e-7, 1e-4)}, True),
        ({"value": 5e-5, "bounds": (1e-7, 1e-4)}, False),
        ({"value": 1.0 + 0.5 * BOUND_TOLERANCE, "bounds": (0.0, 1.0)}, True),
        ({"value": 1.0 - 10 * BOUND_TOLERANCE, "bounds": (0.0, 1.0)}, False),
        # The search space wins over the physical one.
        (
            {
                "value": 5e-5,
                "bounds": (1e-7, 1e-4),
                "transformed_value": -7.0,
                "transformed_bounds": (-7.0, -4.0),
            },
            True,
        ),
        ({"value": 3.0}, False),
        ({"value": 3.0, "bounds": (1.0,)}, False),
        ("not a mapping", False),
        (None, False),
    ],
)
def test_a_parameter_is_on_a_bound_within_the_tolerance_of_its_range(
    payload: object, expected: bool
) -> None:
    assert on_bound(payload) is expected


def _session(tmp_path: Path, *, trials: int = 3, best: int | None = 3, **fields) -> Session:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calage", trials=0, best_trial=best, **fields)
    directory = project / "sessions" / "calage"
    statuses = ["completed", "failed", "completed", "infeasible"]
    for number in range(1, trials + 1):
        append_trial(
            directory,
            trial_line(
                number,
                case="calage",
                phase="steady_k",
                status=statuses[number - 1],
                params={"K": BOUNDED if number == best else {"value": 5e-5}},
            ),
        )
    return Session(directory)


@pytest.mark.parametrize(
    ("changes", "label", "text"),
    [
        ({"stop": "met its rule, converged"}, "search stopped", "met its rule, converged"),
        ({"bounds_reached": ()}, "bounds reached", "none"),
        ({"bounds_reached": ("K", "n")}, "bounds reached", "K, n"),
        ({"trials_by_status": {}}, "trials", "none"),
        ({"best_cost": None}, "best trial", "3, cost not scored"),
        ({"cost_label": "1 - nse"}, "best trial", "3, cost 0.08 (1 - nse)"),
    ],
)
def test_a_row_reads_its_field(changes: dict, label: str, text: str) -> None:
    base = SessionSummary(
        name="calage",
        method="tpe",
        status="completed",
        trials_by_status={"completed": 3},
        best_trial=3,
        best_cost=0.08,
        cost_label=None,
        scored_on=None,
        stop=None,
        bounds_reached=(),
        calibrated_variable="discharge",
        report=None,
        profile=(),
    )
    assert dict(summary_rows(replace(base, **changes)))[label] == text
