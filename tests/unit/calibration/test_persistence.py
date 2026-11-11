"""Tests of `persistence`: the session documents and the trial journal it writes."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import ParamSuggestion
from hydromodpy.calibration.persistence import (
    DEFAULT_PHASE,
    CalibrationPersistence,
    PersistDetail,
    PhaseContext,
    scored_window,
)
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION, PeriodWindow
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.session.descriptor import ParameterWidth, ScoredSamples, read_session
from hydromodpy.results.session.journal import trials_path
from hydromodpy.results.session.phase import read_phase
from hydromodpy.results.storage.run_profile import ProfileLine
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


def test_the_best_trial_is_asked_of_one_phase_and_one_restart(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    for name, restart, cost in (("a", 0, 0.1), ("b", 0, 0.5), ("b", 1, 0.3)):
        journal_trial(session, 1, cost, phase=PhaseContext(name, 0, restart))

    assert session.best_trial("b").cost == 0.3
    assert session.best_trial("b", restart=0).cost == 0.5
    assert session.best_trial(restart=1).cost == 0.3


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


def test_the_closing_of_a_session_and_of_a_phase_keeps_every_field_it_is_given(
    tmp_path: Path,
) -> None:
    session = make_session(tmp_path)
    context = PhaseContext(DEFAULT_PHASE, 0, 0)
    session.start_phase(context, frozen={}, cost_name="rmse", cost_label="RMSE")
    for restart in (0, 2):
        journal_trial(session, 1, 0.3, phase=PhaseContext(DEFAULT_PHASE, 0, restart))
    best = session.best_pointer(session.best_trial())
    fields = {
        "scored": _SCORED,
        "stop_state": "rule_met",
        "stopping_rule": "xtol",
        "stop_note": "frozen",
        "widths": _WIDTHS,
    }

    phase = session.finish_phase(DEFAULT_PHASE, status="completed", best=best, **fields)
    closed = session.finalize_session(
        status="failed", best=best, error="boom", root_search={"bracket": 1}, **fields
    )

    for descriptor in (
        read_phase(session.directory, DEFAULT_PHASE),
        read_session(session.directory),
    ):
        assert (descriptor.best, descriptor.scored, descriptor.widths) == (best, _SCORED, _WIDTHS)
        assert (descriptor.stop_state, descriptor.stopping_rule, descriptor.stop_note) == (
            "rule_met",
            "xtol",
            "frozen",
        )
    assert (phase.status, phase.restarts) == ("completed", 2)
    assert (closed.cost_name, closed.error_message) == ("rmse", "boom")
    assert closed.cases[closed.case_id].cost_name == "rmse"
    assert closed.root_search == {"bracket": 1}
    assert closed.ended_at is not None and closed.ended_at.tzinfo is not None
    assert closed.ended_at == read_outcome(session.directory).ended_at


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


def test_the_finished_line_reads_the_batch_and_the_instant_of_its_proposal(
    tmp_path: Path,
) -> None:
    persistence = make_session(tmp_path)
    persistence.propose(_batch(1, 2), batch=4)
    proposed_at = _events(persistence)[0]["proposed_at"]

    line = journal_trial(persistence, 2, 0.3)

    assert (line.event, line.trial, line.batch) == ("finished", 2, 4)
    assert line.proposed_at == datetime.fromisoformat(proposed_at)
    folded = persistence.trials()
    assert [(t.trial, t.event, t.status) for t in folded] == [
        (1, "proposed", "running"),
        (2, "finished", "completed"),
    ]
    assert persistence.best_trial().trial == 2


def test_a_trial_never_proposed_finishes_without_a_batch(tmp_path: Path) -> None:
    line = journal_trial(make_session(tmp_path), 1)
    assert (line.batch, line.proposed_at) == (None, None)


WINDOWS: tuple[tuple[str, PhaseContext, str], ...] = (
    ("the default phase", PhaseContext(), "calibration"),
    ("a named window", PhaseContext("transient", 1, window="spring"), "spring"),
)


@pytest.mark.parametrize(("case", "phase", "window"), WINDOWS, ids=[c for c, *_ in WINDOWS])
def test_each_case_carries_the_rule_and_the_window_of_its_phase(
    tmp_path: Path, case: str, phase: PhaseContext, window: str
) -> None:
    del case
    line = journal_trial(make_session(tmp_path), 1, phase=phase)
    assert (line.only_case.rule, line.only_case.window) == (METRIC_RULE_VERSION, window)
    assert METRIC_RULE_VERSION == "2"


def test_scored_window_names_the_period_of_role_calibration() -> None:
    day = date(2020, 1, 1)
    windows = {
        "check": PeriodWindow(role="validation", start=day, end=day),
        "spring": PeriodWindow(role="calibration", start=day, end=day),
    }
    assert scored_window(windows) == "spring"
    assert scored_window({}) == "calibration"


def test_the_profile_of_a_trial_goes_in_its_finished_line(tmp_path: Path) -> None:
    from tests._helpers.session_documents import NOW

    solve = ProfileLine(kind="solve", name="flow", attempt=1, started_at=NOW, duration_s=0.2)
    line = journal_trial(make_session(tmp_path), 1, metadata={"profile": [solve]})
    assert line.profile == [solve]


def test_a_trial_read_from_the_cache_has_an_empty_profile(tmp_path: Path) -> None:
    from tests._helpers.session_documents import NOW

    solve = ProfileLine(kind="solve", name="flow", attempt=1, started_at=NOW, duration_s=0.2)
    line = journal_trial(make_session(tmp_path), 1, from_cache=True, metadata={"profile": [solve]})
    assert line.profile == []


def test_link_trial_writes_a_linked_line_that_wins(tmp_path: Path) -> None:
    persistence = make_session(tmp_path)
    persistence.propose(_batch(1), batch=1)
    journal_trial(persistence, 1)
    persistence.link_trial(1, sim_id="c" * 32, rel_dir="runs/calage")

    assert [line["event"] for line in _events(persistence)] == ["proposed", "finished", "linked"]
    (trial,) = persistence.trials()
    assert (trial.event, trial.only_case.sim_id) == ("linked", "c" * 32)


def test_record_optimizer_keeps_the_seed_and_adds_each_restart_seed(tmp_path: Path) -> None:
    persistence = make_session(tmp_path)
    persistence.record_optimizer("main", seed=11)
    persistence.record_optimizer("main", options={"sampler": "tpe"}, restart_seeds={"0": 11})
    persistence.record_optimizer("main", restart_seeds={"1": 12})

    block = read_session(persistence.directory).optimizer["main"]
    assert (block.seed, block.options) == (11, {"sampler": "tpe"})
    assert block.restart_seeds == {"0": 11, "1": 12}


def test_a_descriptor_without_optimizer_reads_none(tmp_path: Path) -> None:
    assert read_session(make_session(tmp_path).directory).optimizer is None
