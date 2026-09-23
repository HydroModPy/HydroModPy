"""Unit tests for the NDJSON progress sink.

Boundary-spec.md 1.5 / F4g item 12: the sink is a second, independent
observer of ``core.progress``'s call sites, fed even when the rich renderer
is disabled (no terminal), which is exactly the case under an orchestrator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from hydromodpy.core import progress as core_progress
from hydromodpy.core import progress_ndjson


@pytest.fixture(autouse=True)
def _reset_ndjson_handle(monkeypatch):
    """Every test starts with no cached file handle from a previous one."""
    monkeypatch.setattr(progress_ndjson, "_open_path", None, raising=False)
    monkeypatch.setattr(progress_ndjson, "_open_handle", None, raising=False)
    monkeypatch.delenv(progress_ndjson.ENV_VAR, raising=False)
    yield


def _read_events(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_emit_is_a_noop_without_the_env_var(tmp_path: Path):
    progress_ndjson.emit(1, "probe", completed=0.0, total=1.0, state="started")
    assert list(tmp_path.iterdir()) == []


def test_emit_appends_one_json_line_with_the_contract_fields(tmp_path, monkeypatch):
    """boundary-spec.md 1.5: ts, stage, step, of, percent, message, plus
    task_id and state, which the spec's fields do not carry."""
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


def test_emit_percent_is_none_without_a_known_total(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    progress_ndjson.emit(1, "Loading climate data", completed=None, total=None, state="started")

    event = _read_events(target)[0]
    assert event["percent"] is None
    assert event["step"] is None
    assert event["of"] is None


def test_emit_flushes_every_line_immediately(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")
    # Read back before any explicit close: a crash right here must not lose it.
    assert len(_read_events(target)) == 1
    progress_ndjson.emit(1, "a", completed=None, total=None, state="completed")
    assert len(_read_events(target)) == 2


def test_new_task_id_is_monotonic_and_unique():
    a = progress_ndjson.new_task_id()
    b = progress_ndjson.new_task_id()
    assert b > a


def test_switching_the_env_var_reopens_a_different_file(tmp_path, monkeypatch):
    """A chain runs several jobs in one process, one file per job."""
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
    """Force a non-interactive console, the orchestrated-run case."""
    import io

    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=False, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    core_progress.set_console_mode("verbose")
    yield buffer


def test_phase_feeds_the_sink_even_when_rendering_is_disabled(
    disabled_console, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    with core_progress.phase("Loading climate data"):
        pass

    events = _read_events(target)
    states = [event["state"] for event in events]
    assert states == ["started", "completed"]
    assert all(event["message"] == "Loading climate data" for event in events)
    assert disabled_console.getvalue() == ""
    captured = capsys.readouterr()
    assert captured.out == ""


def test_phase_marks_the_sink_event_failed_on_an_exception(disabled_console, tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    with pytest.raises(ValueError):
        with core_progress.phase("Broken step"):
            raise ValueError("boom")

    events = _read_events(target)
    assert [event["state"] for event in events] == ["started", "failed"]


def test_task_feeds_progress_events_on_every_advance(disabled_console, tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    with core_progress.task("Counting", total=3) as handle:
        for _ in range(3):
            handle.advance()

    events = _read_events(target)
    assert [event["state"] for event in events] == [
        "started",
        "progress",
        "progress",
        "progress",
        "completed",
    ]
    assert [event["step"] for event in events] == [0.0, 1.0, 2.0, 3.0, 3.0]
    assert all(event["of"] == 3.0 for event in events)
    # Every event of one task shares its task_id: a supervisor tails one stream
    # per task by grouping on it.
    assert len({event["task_id"] for event in events}) == 1


def test_emit_swallows_oserror_from_an_unwritable_path(tmp_path, monkeypatch):
    """A misconfigured sink must not raise: it is observability, not the run."""
    bad_path = tmp_path / "does-not-exist" / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(bad_path))

    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")

    assert not bad_path.parent.exists()


def test_phase_body_runs_when_the_sink_path_is_unwritable(tmp_path, monkeypatch):
    """A bad HMP_PROGRESS_FILE must not stop the capability it observes."""
    bad_path = tmp_path / "does-not-exist" / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(bad_path))
    ran = []

    with core_progress.phase("Loading climate data"):
        ran.append("body")

    assert ran == ["body"]


def test_renderer_is_unchanged_on_a_terminal_when_the_sink_path_is_unwritable(
    tmp_path, monkeypatch
):
    """The task's own acceptance criterion: a broken sink must not touch the renderer."""
    import io

    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=True, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    monkeypatch.delenv("HMP_NO_PROGRESS", raising=False)
    core_progress.set_console_mode("verbose")
    bad_path = tmp_path / "does-not-exist" / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(bad_path))
    ran = []

    with core_progress.phase("Loading climate data"):
        ran.append("body")

    assert ran == ["body"]
    output = buffer.getvalue()
    assert "✓" in output
    assert "Loading climate data" in output


def test_renderer_output_is_unchanged_when_a_terminal_is_present(tmp_path, monkeypatch):
    """The sink is fed alongside the renderer, never instead of it."""
    import io

    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=True, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    monkeypatch.delenv("HMP_NO_PROGRESS", raising=False)
    core_progress.set_console_mode("verbose")
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    with core_progress.phase("Loading climate data"):
        pass

    output = buffer.getvalue()
    assert "✓" in output
    assert "Loading climate data" in output
    events = _read_events(target)
    assert [event["state"] for event in events] == ["started", "completed"]


def test_emit_is_a_noop_when_suppressed(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    progress_ndjson.emit(1, "trial", completed=None, total=None, state="started", suppressed=True)

    assert not target.exists()


def test_a_task_acquired_inside_suppressed_writes_nothing(disabled_console, tmp_path, monkeypatch):
    """Calibration trials, sweep children: muted on the console, muted here too."""
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))

    with core_progress.suppressed():
        with core_progress.task("trial 1", total=2) as handle:
            handle.advance()
            handle.advance()

    assert not target.exists()


def test_the_outer_task_keeps_writing_through_a_suppressed_inner_run(
    disabled_console, tmp_path, monkeypatch
):
    """The outer progress (the calibration itself) is acquired before the
    suppressed block and is not silenced by it."""
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


def test_close_at_exit_closes_the_cached_handle(tmp_path, monkeypatch):
    target = tmp_path / "progress.ndjson"
    monkeypatch.setenv(progress_ndjson.ENV_VAR, str(target))
    progress_ndjson.emit(1, "a", completed=None, total=None, state="started")
    assert progress_ndjson._open_handle is not None

    progress_ndjson._close_at_exit()

    assert progress_ndjson._open_handle is None
    assert progress_ndjson._open_path is None


def test_close_at_exit_is_a_noop_with_nothing_open():
    progress_ndjson._close_at_exit()
    assert progress_ndjson._open_handle is None
