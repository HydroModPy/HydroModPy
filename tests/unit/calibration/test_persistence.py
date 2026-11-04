"""Tests of `persistence`."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.persistence import CalibrationPersistence, PersistDetail, PhaseContext
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


def test_the_unread_trial_stays_in_the_journal(tmp_path: Path) -> None:
    trials = _session(tmp_path, detail="none").trials()

    assert [line.trial for line in trials] == [1, 2, 3]
    assert [line.speculative_unused for line in trials] == [False, True, False]


def test_a_tie_across_restarts_goes_to_the_lower_restart_whatever_the_arrival(
    tmp_path: Path,
) -> None:
    """Restarts side by side number their trials as the batches arrive, so numbers cannot break it."""
    session = make_session(tmp_path)
    for restart in (1, 0):
        journal_trial(session, 1, 0.5, phase=PhaseContext(restart=restart))

    best = session.best_trial()

    assert (best.restart, best.trial) == (0, 2)


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
