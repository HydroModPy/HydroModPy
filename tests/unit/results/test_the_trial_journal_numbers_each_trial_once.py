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
    TRIAL_VERSIONS,
    TrialCase,
    TrialLine,
    append_trial,
    next_trial_number,
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


def test_a_proposed_trial_alone_has_no_cost_and_still_takes_its_number(tmp_path):
    _write(tmp_path, [_event(1, "finished"), _event(2, "proposed")])
    proposed = read_trials(tmp_path)[-1]
    assert (proposed.trial, proposed.status, proposed.cost, proposed.cases) == (
        2,
        "running",
        None,
        {},
    )
    assert next_trial_number(tmp_path) == 3


def _v2_payload(trial: int, **overrides: Any) -> dict[str, Any]:
    """Return a line as a pre-release wrote it: no event, batch, rule, window nor profile."""
    payload = json.loads(json.dumps(_line(trial, "k_grid").model_dump(mode="json", by_alias=True)))
    for key in ("event", "batch", "proposed_at", "profile"):
        payload.pop(key)
    for case in payload["cases"].values():
        case.pop("rule")
        case.pop("window")
    return {**payload, "schema": "hydromodpy.trial.v2", **overrides}


def test_a_line_of_a_pre_release_reads_as_a_finished_trial(tmp_path):
    trials_path(tmp_path).write_text(json.dumps(_v2_payload(1)) + "\n", encoding="utf-8")
    (trial,) = read_trials(tmp_path)
    assert (trial.schema_, trial.event, trial.batch, trial.proposed_at, trial.profile) == (
        "hydromodpy.trial.v2",
        "finished",
        None,
        None,
        [],
    )
    assert (trial.only_case.rule, trial.only_case.window) == (None, None)
    assert TRIAL_VERSIONS.oldest == "hydromodpy.trial.v2"
    assert TRIAL_VERSIONS.current == TRIAL_SCHEMA


def test_a_journal_that_mixes_old_and_new_lines_reads_line_by_line(tmp_path):
    trials_path(tmp_path).write_text(json.dumps(_v2_payload(1)) + "\n", encoding="utf-8")
    _write(tmp_path, [_event(2, "proposed"), _event(2, "finished"), _event(1, "linked")])
    trials = read_trials(tmp_path)
    assert [(t.trial, t.schema_, t.event) for t in trials] == [
        (1, TRIAL_SCHEMA, "linked"),
        (2, TRIAL_SCHEMA, "finished"),
    ]


def test_a_line_of_a_pre_release_read_and_written_again_keeps_its_schema_and_later_keys(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    payload = _v2_payload(1, written_later={"by": "2.9"})
    trials_path(source).write_text(json.dumps(payload) + "\n", encoding="utf-8")
    (trial,) = read_trials(source)
    append_trial(target, trial)
    written = json.loads(trials_path(target).read_text(encoding="utf-8"))
    assert written["schema"] == "hydromodpy.trial.v2"
    assert written["written_later"] == {"by": "2.9"}


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


def test_a_trial_without_a_solve_line_has_no_solve_time_in_its_row():
    (row,) = trial_rows(_line(1, "main"))
    assert (row["batch"], row["rule"], row["window"], row["solve_s"], row["reused"]) == (
        None,
        None,
        None,
        None,
        None,
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


def test_a_line_of_a_later_version_is_refused_naming_its_line(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k"))
    path = trials_path(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace(TRIAL_SCHEMA, "hydromodpy.trial.v4"))

    with pytest.raises(SchemaVersionMismatchError, match=r"trials\.jsonl:1 has schema"):
        read_trials(tmp_path)


def test_the_trial_number_is_unique_and_monotone_across_phases_and_restarts(tmp_path):
    assert next_trial_number(tmp_path) == 1
    for trial in (1, 2, 3):
        append_trial(tmp_path, _line(trial, "steady_k"))
    assert next_trial_number(tmp_path) == 4
    append_trial(tmp_path, _line(4, "transient_sy"))
    append_trial(tmp_path, _line(5, "transient_sy", restart=1))
    assert next_trial_number(tmp_path) == 6

    trials = read_trials(tmp_path)
    assert [t.trial for t in trials] == [1, 2, 3, 4, 5]
    assert [t.phase for t in trials] == ["steady_k"] * 3 + ["transient_sy"] * 2
    assert trials[-1].restart == 1
    assert trials_path(tmp_path) == tmp_path / "trials.jsonl"


def test_the_last_line_of_a_trial_wins_at_an_equal_event(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k", status="running", ended_at=None, cost=None))
    append_trial(tmp_path, _line(2, "steady_k"))
    append_trial(tmp_path, _line(1, "steady_k", sim_id="9a4f" * 8, rel_dir="runs/J0014010-calage"))

    trials = read_trials(tmp_path)
    assert [t.trial for t in trials] == [1, 2]
    assert trials[0].status == "completed"
    assert trials[0].only_case.sim_id == "9a4f" * 8
    assert trials[0].only_case.rel_dir == "runs/J0014010-calage"
    assert sum(1 for _ in trials_path(tmp_path).read_text(encoding="utf-8").splitlines()) == 3


def test_a_cut_last_write_is_not_a_trial(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k"))
    with trials_path(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write('{"trial": 2, "phase": "stea')

    assert [t.trial for t in read_trials(tmp_path)] == [1]
    assert next_trial_number(tmp_path) == 2


def test_a_broken_complete_line_is_an_error_that_names_its_line(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k"))
    with trials_path(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write("not json\n")

    with pytest.raises(ValueError, match="trials.jsonl:2 is not a trial line"):
        read_trials(tmp_path)


def test_a_session_without_journal_has_no_trials(tmp_path):
    assert read_trials(tmp_path) == []


def test_a_line_round_trips_with_its_components_and_params(tmp_path):
    line = _line(3, "transient_sy", restart=2, components={"nse": 0.7, "kge": 0.6})
    append_trial(tmp_path, line)
    assert read_trials(tmp_path) == [line]
    assert json.loads(trials_path(tmp_path).read_text(encoding="utf-8"))["schema"] == TRIAL_SCHEMA
    assert TRIAL_SCHEMA == "hydromodpy.trial.v3"
    assert physical_parameters(line) == {"K": pytest.approx(3e-5)}


def test_a_trial_below_one_or_an_unknown_status_is_refused():
    with pytest.raises(ValidationError, match="trial"):
        _line(0, "steady_k")
    with pytest.raises(ValidationError, match="status"):
        _line(1, "steady_k", status="done")


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="objective"):
        TrialLine.model_validate({**_line(1, "p").model_dump(), "objective": 0.1})


def test_a_line_of_a_pre_release_is_refused_naming_its_file_and_line(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k"))
    path = trials_path(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace(TRIAL_SCHEMA, "hydromodpy.trial.v1"))

    with pytest.raises(
        SchemaVersionMismatchError, match=r"trials\.jsonl:1 holds .*written by a pre-release"
    ):
        read_trials(tmp_path)


def test_a_trial_of_two_cases_gives_one_row_per_case_and_names_no_single_one():
    line = _line(2, "main", cost=0.4)
    line = line.model_copy(
        update={
            "cases": {
                "a": TrialCase(cost=0.3, components={"nse": 0.7}, status="completed"),
                "b": TrialCase(cost=0.5, status="failed", error="dry"),
            }
        }
    )

    rows = list(trial_rows(line))

    assert line.only_case is None
    assert [(r["case_id"], r["cost"], r["case_cost"], r["case_status"]) for r in rows] == [
        ("a", 0.4, 0.3, "completed"),
        ("b", 0.4, 0.5, "failed"),
    ]
    assert rows[0]["components"] == {"nse": 0.7}
    assert rows[0]["duration_s"] == 0.0


def test_a_trial_that_names_no_case_gives_one_row_without_a_case():
    line = _line(1, "main").model_copy(update={"cases": {}})
    (row,) = trial_rows(line)
    assert (row["case_id"], row["case_cost"], row["components"], row["from_cache"]) == (
        None,
        None,
        {},
        False,
    )


def test_a_trial_rel_dir_follows_the_one_grammar():
    with pytest.raises(ValidationError, match="not a result directory"):
        _line(1, "steady_k", rel_dir="/abs/sessions/c/trials/0001")
    assert _line(1, "steady_k", rel_dir="sessions/c/trials/0001/case").only_case.rel_dir == (
        "sessions/c/trials/0001/case"
    )
