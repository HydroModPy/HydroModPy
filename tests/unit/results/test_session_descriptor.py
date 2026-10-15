"""The session and phase descriptors are written whole and read back typed."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.session.descriptor import (
    SESSION_SCHEMA,
    BestTrial,
    SessionDescriptor,
    read_session,
    session_descriptor_path,
    write_session,
)
from hydromodpy.results.session.phase import (
    PhaseDescriptor,
    list_phases,
    phase_dir,
    read_phase,
    write_phase,
)
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME, SESSION_PHASES_DIRNAME

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)


def _descriptor(**overrides) -> SessionDescriptor:
    payload = {
        "site": "J0014010",
        "session_id": "sess0001",
        "case_id": "J0014010-calage",
        "config_hash": "c0ffee" * 10 + "c0ff",
        "hydromodpy_version": "2.0.0a5",
        "method": "tpe",
        "search_space": {"K": {"bounds": [1e-7, 1e-4], "transform": "log"}},
        "objective_name": "nse_log",
        "started_at": NOW,
    }
    payload.update(overrides)
    return SessionDescriptor(**payload)


def test_a_descriptor_round_trips_and_names_its_schema(tmp_path):
    descriptor = _descriptor(
        status="completed",
        ended_at=NOW,
        best=BestTrial(trial=7, sim_id="9a4f" * 8, rel_dir="runs/J0014010-calage", objective=-0.84),
    )
    write_session(tmp_path, descriptor)

    assert read_session(tmp_path) == descriptor
    text = session_descriptor_path(tmp_path).read_text(encoding="utf-8")
    assert text.startswith('{\n  "schema": "hydromodpy.session.v3"')
    assert '"site": "J0014010"' in text


def test_a_fresh_descriptor_is_running_without_a_best(tmp_path):
    descriptor = _descriptor()
    assert (
        descriptor.status == "running" and descriptor.best is None and descriptor.ended_at is None
    )


def test_the_descriptor_is_rewritten_whole_and_flushed(tmp_path, monkeypatch):
    synced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    write_session(tmp_path, _descriptor())
    write_session(tmp_path, _descriptor(status="aborted", ended_at=NOW, best=BestTrial(trial=4)))

    assert read_session(tmp_path).status == "aborted"
    assert read_session(tmp_path).best.trial == 4
    assert [p.name for p in tmp_path.iterdir()] == [SESSION_DESCRIPTOR_FILENAME]
    assert len(synced) == 4


def test_a_running_session_cannot_have_ended():
    with pytest.raises(ValidationError, match="running session has no ended_at"):
        _descriptor(ended_at=NOW)


def test_another_schema_or_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match=SESSION_SCHEMA):
        SessionDescriptor.model_validate(
            {**_descriptor().model_dump(by_alias=True), "schema": "v2"}
        )
    with pytest.raises(ValidationError, match="best_trial"):
        SessionDescriptor.model_validate(
            {**_descriptor().model_dump(by_alias=True), "best_trial": 3}
        )


def test_phase_descriptors_live_under_phases_and_list_by_index(tmp_path):
    second = PhaseDescriptor(
        phase_id="p2",
        name="transient_sy",
        index=1,
        status="running",
        frozen={"K": 6.1e-6, "from": "steady_k"},
        restarts=1,
    )
    first = PhaseDescriptor(
        phase_id="p1",
        name="steady_k",
        index=0,
        status="completed",
        best=BestTrial(trial=3, objective=0.2),
    )
    write_phase(tmp_path, second)
    write_phase(tmp_path, first)

    assert phase_dir(tmp_path, "steady_k") == tmp_path / SESSION_PHASES_DIRNAME / "steady_k"
    assert read_phase(tmp_path, "transient_sy") == second
    assert [phase.name for phase in list_phases(tmp_path)] == ["steady_k", "transient_sy"]
    assert list_phases(tmp_path / "elsewhere") == []


def test_a_phase_name_is_a_directory_name():
    with pytest.raises(ValidationError, match="name"):
        PhaseDescriptor(phase_id="p", name="steady k", index=0)


def test_the_descriptor_carries_the_window_it_scored_its_objective_on(tmp_path):
    window = DateWindow(start="2016-01-01", end="2018-12-31")
    write_session(tmp_path, _descriptor(objective_window=window))
    assert read_session(tmp_path).objective_window == window
    assert _descriptor().objective_window is None


@pytest.mark.parametrize("rel_dir", ["/abs/runs/x", "runs/../x", "share/x"])
def test_a_best_trial_rel_dir_follows_the_one_grammar(rel_dir):
    with pytest.raises(ValidationError, match="not a result directory"):
        BestTrial(trial=1, rel_dir=rel_dir)
    assert BestTrial(trial=1, rel_dir="sessions/c/trials/0001").rel_dir == "sessions/c/trials/0001"
