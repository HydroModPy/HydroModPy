"""Session documents and the trial journal written by `persistence`.

A calibration session lives in one folder. It holds a descriptor, an outcome, a
heartbeat and a journal with one JSON line per trial event. Costs are
dimensionless, parameter values are in the unit given with them (m/s for K).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import ParamSuggestion
from hydromodpy.calibration.persistence import (
    CalibrationPersistence,
    PersistDetail,
    scored_window,
)
from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.session.journal import trials_path
from tests.unit.calibration._factories_runners import journal_trial, make_session

DAY = date(2020, 1, 1)


def session_with_an_unread_trial(tmp_path: Path, detail: PersistDetail) -> CalibrationPersistence:
    # Trial 2 has the lowest cost but a speculative engine solved it and never read it.
    unread = {"metadata": {"speculative_unused": True}}
    costs = ((1.0, {}), (0.2, unread), (0.5, {}))
    return make_session(
        tmp_path, "toy", costs=tuple({"cost": c, "detail": detail, **extra} for c, extra in costs)
    )


def describe(values):
    return {name: {"value": value, "units": "m/s"} for name, value in values.items()}


def suggestions(*trial_ids: int) -> list[ParamSuggestion]:
    return [ParamSuggestion(trial_id=i, values={"K": 1e-5 * i}) for i in trial_ids]


def journal_events(persistence: CalibrationPersistence) -> list[dict]:
    text = trials_path(persistence.directory).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


@pytest.mark.parametrize("detail", ["none", "summary", "full"])
def test_best_trial_ignores_unread_trials(tmp_path: Path, detail: PersistDetail) -> None:
    best = session_with_an_unread_trial(tmp_path, detail).best_trial()

    assert best is not None
    assert best.trial == 3


def test_session_exists_with_a_descriptor(tmp_path: Path) -> None:
    assert not CalibrationPersistence(tmp_path / "none").exists()
    assert make_session(tmp_path).exists()


def test_pulse(tmp_path: Path) -> None:
    unopened = CalibrationPersistence(tmp_path / "none")
    unopened.start_pulse()
    unopened.stop_pulse()
    assert not (tmp_path / "none" / "logs" / "heartbeat.json").exists()

    session = make_session(tmp_path)
    session.start_pulse()
    session.start_pulse()
    session.stop_pulse()
    session.stop_pulse()

    assert (session.directory / "logs" / "heartbeat.json").is_file()


def test_closing_an_unopened_session_writes_no_outcome(tmp_path: Path) -> None:
    opened = make_session(tmp_path)
    outcome = (opened.directory / "outcome.json").read_bytes()

    closed = CalibrationPersistence(opened.directory).finalize_session(status="failed", best=None)

    assert closed.status == "failed"
    assert (opened.directory / "outcome.json").read_bytes() == outcome


@pytest.mark.parametrize(
    ("detail", "kept"),
    [("none", {}), ("summary", {"materialized_overlay": "ov.toml"})],
)
def test_overlay_of_a_trial(tmp_path: Path, detail: PersistDetail, kept: dict) -> None:
    session = make_session(tmp_path)

    line = journal_trial(session, 1, detail=detail, metadata={"materialized_overlay": "ov.toml"})

    assert line.cases[session.case_id].detail == kept


def test_propose_numbers_a_batch(tmp_path: Path) -> None:
    persistence = make_session(tmp_path)
    numbers = persistence.propose(suggestions(7, 3), batch=1, parameters=describe)
    numbers += persistence.propose(suggestions(9), batch=2, parameters=describe)

    assert numbers == [1, 2, 3]
    lines = journal_events(persistence)
    assert [(line["event"], line["trial"], line["batch"]) for line in lines] == [
        ("proposed", 1, 1),
        ("proposed", 2, 1),
        ("proposed", 3, 2),
    ]
    assert all(line["status"] == "running" and line["cost"] is None for line in lines)
    assert lines[0]["params"]["K"]["value"] == pytest.approx(7e-5)
    assert lines[0]["params"]["K"]["units"] == "m/s"
    assert lines[0]["proposed_at"] == lines[1]["proposed_at"]


def test_propose_writes_a_trial_once(tmp_path: Path) -> None:
    persistence = make_session(tmp_path)
    persistence.propose(suggestions(1), batch=1)
    persistence.propose(suggestions(1), batch=2)

    assert [line["batch"] for line in journal_events(persistence)] == [1]


def test_scored_window() -> None:
    windows = {
        "check": PeriodWindow(role="validation", start=DAY, end=DAY),
        "spring": PeriodWindow(role="calibration", start=DAY, end=DAY),
    }
    assert scored_window(windows) == "spring"
    assert scored_window({}) == "calibration"
