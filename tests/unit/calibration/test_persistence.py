"""Tests of `persistence`: the session documents and the trial journal it writes."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import ParamSuggestion
from hydromodpy.calibration.persistence import (
    CalibrationPersistence,
    PersistDetail,
    PhaseContext,
    scored_window,
)
from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.session.descriptor import ParameterWidth, ScoredSamples
from hydromodpy.results.session.journal import trials_path
from tests.unit.calibration._factories_runners import journal_trial, make_session

# From test_the_best_trial_is_on_the_path_of_the_search.py
# The best trial of a session is one the search read.
#
# A speculative engine (Nelder-Mead with ``parallel > 1``) solves candidates its
# rules then leave unread. Such a trial is real and kept, but the search froze
# on the best point it read. ``best_trial`` took the minimum over every
# completed trial, so a lower unread one became the promoted run, a point the
# search never returned.


def _session(tmp_path: Path, *, detail: PersistDetail) -> CalibrationPersistence:
    unread = {"metadata": {"speculative_unused": True}}
    return make_session(
        tmp_path,
        "toy",
        costs=tuple(
            {"cost": cost, "detail": detail, **extra}
            for cost, extra in ((1.0, {}), (0.2, unread), (0.5, {}))
        ),
    )


@pytest.mark.parametrize("detail", ["none", "summary", "full"])
def test_an_unread_speculative_trial_is_not_the_best(tmp_path: Path, detail: PersistDetail) -> None:
    best = _session(tmp_path, detail=detail).best_trial()

    assert best is not None
    assert best.trial == 3


def test_a_directory_without_a_descriptor_does_not_exist_as_a_session(tmp_path: Path) -> None:
    assert not CalibrationPersistence(tmp_path / "none").exists()
    assert make_session(tmp_path).exists()


def test_the_pulse_runs_only_once_the_session_is_open_and_stops_when_asked(
    tmp_path: Path,
) -> None:
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


def test_a_session_closed_by_a_writer_that_never_opened_it_writes_no_outcome(
    tmp_path: Path,
) -> None:
    opened = make_session(tmp_path)
    outcome = (opened.directory / "outcome.json").read_bytes()

    closed = CalibrationPersistence(opened.directory).finalize_session(status="failed", best=None)

    assert closed.status == "failed"
    assert (opened.directory / "outcome.json").read_bytes() == outcome


@pytest.mark.parametrize(
    ("detail", "kept"),
    [("none", {}), ("summary", {"materialized_overlay": "ov.toml"})],
)
def test_the_overlay_a_trial_ran_on_is_kept_from_the_summary_up(
    tmp_path: Path, detail: PersistDetail, kept: dict
) -> None:
    session = make_session(tmp_path)

    line = journal_trial(session, 1, detail=detail, metadata={"materialized_overlay": "ov.toml"})

    assert line.cases[session.case_id].detail == kept


_SCORED = [ScoredSamples(window="calibration", case_id="calage", output="head", n=3)]
_WIDTHS = {"K": ParameterWidth(sigma=2.0)}


# -- the trial journal in events ------------------------------------------------


def _describe(values):
    return {name: {"value": value, "units": "m/s"} for name, value in values.items()}


def _batch(*trial_ids: int) -> list[ParamSuggestion]:
    return [
        ParamSuggestion(trial_id=trial_id, values={"K": 1e-5 * trial_id}) for trial_id in trial_ids
    ]


def _events(persistence: CalibrationPersistence) -> list[dict]:
    text = trials_path(persistence.directory).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_propose_numbers_a_batch_in_its_order_and_writes_one_line_per_trial(
    tmp_path: Path,
) -> None:
    persistence = make_session(tmp_path)
    numbers = persistence.propose(_batch(7, 3), batch=1, parameters=_describe)
    numbers += persistence.propose(_batch(9), batch=2, parameters=_describe)

    assert numbers == [1, 2, 3]
    lines = _events(persistence)
    assert [(line["event"], line["trial"], line["batch"]) for line in lines] == [
        ("proposed", 1, 1),
        ("proposed", 2, 1),
        ("proposed", 3, 2),
    ]
    assert all(line["status"] == "running" and line["cost"] is None for line in lines)
    assert lines[0]["params"]["K"]["value"] == pytest.approx(7e-5)
    assert lines[0]["params"]["K"]["units"] == "m/s"
    assert lines[0]["proposed_at"] == lines[1]["proposed_at"]


def test_a_trial_proposed_twice_is_written_once(tmp_path: Path) -> None:
    persistence = make_session(tmp_path)
    persistence.propose(_batch(1), batch=1)
    persistence.propose(_batch(1), batch=2)
    assert [line["batch"] for line in _events(persistence)] == [1]


WINDOWS: tuple[tuple[str, PhaseContext, str], ...] = (
    ("the default phase", PhaseContext(), "calibration"),
    ("a named window", PhaseContext("transient", 1, window="spring"), "spring"),
)


def test_scored_window_names_the_period_of_role_calibration() -> None:
    day = date(2020, 1, 1)
    windows = {
        "check": PeriodWindow(role="validation", start=day, end=day),
        "spring": PeriodWindow(role="calibration", start=day, end=day),
    }
    assert scored_window(windows) == "spring"
    assert scored_window({}) == "calibration"
