"""One journal per session, one trial number across phases and restarts, the last line winning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.session.journal import (
    TrialLine,
    append_trial,
    next_trial_number,
    read_trials,
    trials_path,
)

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)


def _line(trial: int, phase: str, **overrides) -> TrialLine:
    payload = {
        "trial": trial,
        "phase": phase,
        "params": {"K": 1e-5 * trial},
        "params_hash": f"v2:{trial:064x}",
        "objective": 0.1 * trial,
        "metrics": {"nse": 1 - 0.1 * trial},
        "status": "completed",
        "started_at": NOW,
        "ended_at": NOW,
    }
    payload.update(overrides)
    return TrialLine(**payload)


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


def test_the_last_line_of_a_trial_wins(tmp_path):
    append_trial(tmp_path, _line(1, "steady_k", status="running", ended_at=None, objective=None))
    append_trial(tmp_path, _line(2, "steady_k"))
    append_trial(tmp_path, _line(1, "steady_k", sim_id="9a4f" * 8, rel_dir="runs/J0014010-calage"))

    trials = read_trials(tmp_path)
    assert [t.trial for t in trials] == [1, 2]
    assert trials[0].status == "completed"
    assert trials[0].sim_id == "9a4f" * 8
    assert trials[0].rel_dir == "runs/J0014010-calage"
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


def test_a_line_round_trips_with_its_metrics_and_params(tmp_path):
    line = _line(3, "transient_sy", restart=2, metrics={"nse": 0.7, "kge": 0.6})
    append_trial(tmp_path, line)
    assert read_trials(tmp_path) == [line]


def test_a_trial_below_one_or_an_unknown_status_is_refused():
    with pytest.raises(ValidationError, match="trial"):
        _line(0, "steady_k")
    with pytest.raises(ValidationError, match="status"):
        _line(1, "steady_k", status="done")


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="objective_value"):
        TrialLine.model_validate({**_line(1, "p").model_dump(), "objective_value": 0.1})


def test_a_trial_rel_dir_follows_the_one_grammar():
    with pytest.raises(ValidationError, match="not a result directory"):
        _line(1, "steady_k", rel_dir="/abs/sessions/c/trials/0001")
    assert _line(1, "steady_k", rel_dir="sessions/c/trials/0001").rel_dir == (
        "sessions/c/trials/0001"
    )
