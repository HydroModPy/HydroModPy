"""The NDJSON progress sink: one JSON line per progress event, written even with no terminal.

It is a second observer of the call sites of ``core.console.progress``, so an
orchestrator can follow a run whose rich display is off.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from hydromodpy.core.console import ndjson as progress_ndjson
from hydromodpy.core.console import progress as core_progress


@pytest.fixture(autouse=True)
def _reset_ndjson_handle(monkeypatch):
    monkeypatch.setattr(progress_ndjson, "_open_path", None, raising=False)
    monkeypatch.setattr(progress_ndjson, "_open_handle", None, raising=False)
    monkeypatch.delenv(progress_ndjson.ENV_VAR, raising=False)
    yield


def _read_events(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_emit_writes_one_json_line(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    progress_ndjson.emit(7, "D8 accumulation", completed=1.0, total=4.0, state="progress")

    events = _read_events(target)
    assert len(events) == 1
    event = events[0]
    for field in ("ts", "stage", "step", "of", "percent", "message", "task_id", "state"):
        assert field in event
    assert event["task_id"] == 7
    assert event["stage"] == "D8 accumulation"
    assert event["message"] == "D8 accumulation"
    assert event["step"] == 1.0
    assert event["of"] == 4.0
    assert event["percent"] == 25.0
    assert event["state"] == "progress"


def test_emit_flushes_each_line(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")
    # Read back before any explicit close: a crash right here must not lose it.
    assert len(_read_events(target)) == 1
    progress_ndjson.emit(1, "a", completed=None, total=None, state="completed")
    assert len(_read_events(target)) == 2


def test_new_env_var_reopens_another_file(tmp_path, monkeypatch):
    # A chain runs several jobs in one process, one file per job.
    first = tmp_path / "job-a" / "progress.ndjson"
    second = tmp_path / "job-b" / "progress.ndjson"
    first.parent.mkdir()
    second.parent.mkdir()

    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(first))
    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")

    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(second))
    progress_ndjson.emit(2, "b", completed=None, total=None, state="started")

    assert len(_read_events(first)) == 1
    assert len(_read_events(second)) == 1


@pytest.fixture
def disabled_console(monkeypatch):
    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=False, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    core_progress.set_console_mode("verbose")
    yield buffer


def test_unwritable_path_is_swallowed(tmp_path, monkeypatch):
    # A misconfigured sink must not raise.
    bad_path = tmp_path / "does-not-exist" / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(bad_path))

    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")

    assert not bad_path.parent.exists()


def test_phase_runs_with_unwritable_sink(tmp_path, monkeypatch):
    bad_path = tmp_path / "does-not-exist" / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(bad_path))
    ran = []

    with core_progress.phase("Loading climate data"):
        ran.append("body")

    assert ran == ["body"]


def test_outer_task_survives_suppressed_inner_run(disabled_console, tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    with core_progress.task("calibration", total=1) as outer:
        with core_progress.suppressed():
            with core_progress.task("trial 1", total=1) as inner:
                inner.advance()
        outer.advance()

    events = _read_events(target)
    assert all(event["message"] == "calibration" for event in events)
    assert [event["state"] for event in events] == ["started", "progress", "completed"]


def test_close_at_exit(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))
    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")
    assert progress_ndjson._open_handle is not None

    progress_ndjson._close_at_exit()

    assert progress_ndjson._open_handle is None
    assert progress_ndjson._open_path is None


def test_close_at_exit_with_nothing_open():
    progress_ndjson._close_at_exit()
    assert progress_ndjson._open_handle is None
