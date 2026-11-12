"""One journal per session, one trial number across phases and restarts, the highest event winning.

A trial is written when it is proposed, when it finishes and when it becomes a
run, each line the whole trial. The reader keeps the highest event of each
number, then the last line at an equal rank. A line of a pre-release reads as finished.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.session.journal import (
    TRIAL_SCHEMA,
    TrialCase,
    TrialLine,
    append_trial,
    physical_parameters,
    read_trials,
    trial_rows,
    trials_path,
)
from hydromodpy.results.storage.run_profile import ProfileLine
from tests._helpers.session_documents import NOW, trial_line


def _line(trial: int, phase: str, **overrides) -> TrialLine:
    fields = {
        "phase": phase,
        "ended_at": NOW,
        "params": {"K": 1e-5 * trial},
        "cost": 0.1 * trial,
        "params_hash": f"v2:{trial:064x}",
        "components": {"nse": 1 - 0.1 * trial},
        **overrides,
    }
    return trial_line(trial, **fields)


def _event(trial: int, event: str, **overrides: Any) -> TrialLine:
    """Return the line of one event of a trial, the way the session writes it."""
    if event == "proposed":
        line = _line(trial, "main", status="running", cost=None, ended_at=None)
        return line.model_copy(
            update={"event": "proposed", "cases": {}, "started_at": None, "batch": 1, **overrides}
        )
    return _line(trial, "main", **overrides).model_copy(update={"event": event, "batch": 1})


def _write(tmp_path, lines: list[TrialLine]) -> None:
    for line in lines:
        append_trial(tmp_path, line)


FOLDS: tuple[tuple[str, list[TrialLine], str, str, float | None, str | None], ...] = (
    (
        "proposed then finished",
        [_event(1, "proposed"), _event(1, "finished")],
        "finished",
        "completed",
        0.1,
        None,
    ),
    (
        "finished then a late proposed",
        [_event(1, "finished"), _event(1, "proposed")],
        "finished",
        "completed",
        0.1,
        None,
    ),
    (
        "finished then linked",
        [_event(1, "proposed"), _event(1, "finished"), _event(1, "linked", sim_id="a" * 32)],
        "linked",
        "completed",
        0.1,
        "a" * 32,
    ),
    (
        "two linked lines, the last wins",
        [_event(1, "linked", sim_id="a" * 32), _event(1, "linked", sim_id="b" * 32)],
        "linked",
        "completed",
        0.1,
        "b" * 32,
    ),
    ("a proposed line alone", [_event(1, "proposed")], "proposed", "running", None, None),
)


@pytest.mark.parametrize(
    ("case", "lines", "event", "status", "cost", "sim_id"), FOLDS, ids=[c for c, *_ in FOLDS]
)
def test_the_reader_keeps_the_highest_event_of_each_trial(
    tmp_path, case, lines, event, status, cost, sim_id
):
    del case
    _write(tmp_path, lines)
    (trial,) = read_trials(tmp_path)
    assert (trial.event, trial.status, trial.cost) == (event, status, cost)
    assert (trial.only_case.sim_id if trial.cases else None) == sim_id


def _v2_payload(trial: int, **overrides: Any) -> dict[str, Any]:
    """Return a line as a pre-release wrote it: no event, batch, rule, window nor profile."""
    payload = json.loads(json.dumps(_line(trial, "k_grid").model_dump(mode="json", by_alias=True)))
    for key in ("event", "batch", "proposed_at", "profile"):
        payload.pop(key)
    for case in payload["cases"].values():
        case.pop("rule")
        case.pop("window")
    return {**payload, "schema": "hydromodpy.trial.v2", **overrides}


def test_a_finished_line_carries_the_whole_trial_rule_window_and_profile_included(tmp_path):
    step = ProfileLine(kind="step", name="run_solver", attempt=1, started_at=NOW, duration_s=0.3)
    solve = ProfileLine(
        kind="solve", name="flow", attempt=1, started_at=NOW, duration_s=0.2, reused="rerun"
    )
    case = TrialCase(cost=0.1, status="completed", rule="2", window="calibration")
    line = _event(1, "finished").model_copy(
        update={
            "cases": {"calage": case},
            "proposed_at": NOW - timedelta(seconds=1),
            "profile": [step, solve],
        }
    )
    append_trial(tmp_path, line)
    (read,) = read_trials(tmp_path)
    assert read == line
    (row,) = trial_rows(read)
    assert (row["batch"], row["rule"], row["window"], row["solve_s"], row["reused"]) == (
        1,
        "2",
        "calibration",
        pytest.approx(0.2),
        "rerun",
    )


REFUSALS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("an unknown event", {"event": "abandoned"}, "event"),
    ("a linked line without a case", {"event": "linked", "cases": {}}, "linked"),
    ("a batch below one", {"batch": 0}, "batch"),
)


@pytest.mark.parametrize(("case", "update", "match"), REFUSALS, ids=[c for c, *_ in REFUSALS])
def test_a_malformed_line_is_refused_by_name(case, update, match):
    del case
    payload = {**_event(1, "finished").model_dump(by_alias=True), **update}
    with pytest.raises(ValidationError, match=match):
        TrialLine.model_validate(payload)


def test_an_unknown_event_read_from_disk_is_refused_naming_its_line(tmp_path):
    append_trial(tmp_path, _event(1, "finished"))
    path = trials_path(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"finished"', '"abandoned"'), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"trials\.jsonl:1 records the event 'abandoned'"):
        read_trials(tmp_path)


def test_a_broken_complete_line_is_an_error_that_names_its_line(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k"))
    with trials_path(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write("not json\n")

    with pytest.raises(ValueError, match="trials.jsonl:2 is not a trial line"):
        read_trials(tmp_path)


def test_a_line_round_trips_with_its_components_and_params(tmp_path):
    line = _line(3, "transient_sy", restart=2, components={"nse": 0.7, "kge": 0.6})
    append_trial(tmp_path, line)
    assert read_trials(tmp_path) == [line]
    assert json.loads(trials_path(tmp_path).read_text(encoding="utf-8"))["schema"] == TRIAL_SCHEMA
    assert TRIAL_SCHEMA == "hydromodpy.trial.v3"
    assert physical_parameters(line) == {"K": pytest.approx(3e-5)}


def test_a_line_of_a_pre_release_is_refused_naming_its_file_and_line(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k"))
    path = trials_path(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace(TRIAL_SCHEMA, "hydromodpy.trial.v1"))

    with pytest.raises(
        SchemaVersionMismatchError, match=r"trials\.jsonl:1 holds .*written by a pre-release"
    ):
        read_trials(tmp_path)
