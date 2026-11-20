"""Console progress: phases, bars and the log handler, drawn on a live terminal or silent when not."""

from __future__ import annotations

import contextlib
import importlib
import io
import logging
import multiprocessing

import pytest
from rich.console import Console
from rich.text import Text

from hydromodpy.core.console import progress as core_progress
from hydromodpy.core.logging import get_logger


@pytest.fixture
def live_console(monkeypatch):
    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=True, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    monkeypatch.delenv("HMP_NO_PROGRESS", raising=False)
    core_progress.set_console_mode("verbose")
    yield buffer
    core_progress.set_console_mode("verbose")


@pytest.fixture
def disabled_console(monkeypatch):
    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=False, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    core_progress.set_console_mode("verbose")
    yield buffer


def test_phase_checkmark(live_console):
    with core_progress.phase("Loading climate data"):
        pass
    output = live_console.getvalue()
    assert "✓" in output
    assert "Loading climate data" in output


def test_phase_cross_on_failure(live_console):
    with pytest.raises(ValueError):
        with core_progress.phase("Broken step"):
            raise ValueError("boom")
    output = live_console.getvalue()
    assert "✗" in output
    assert "Broken step" in output


def test_phase_logs_when_disabled(disabled_console, caplog):
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append
    logger = get_logger("hydromodpy.core.console.progress")
    logger.addHandler(handler)
    try:
        with core_progress.phase("Plain phase"):
            pass
    finally:
        logger.removeHandler(handler)
    infos = [r for r in records if r.levelno == logging.INFO]
    assert any("Plain phase" in r.getMessage() for r in infos)
    assert disabled_console.getvalue() == ""


def test_track_disabled(disabled_console):
    items = list(core_progress.track([1, 2, 3], "Counting"))
    assert items == [1, 2, 3]


def test_track_rendering(live_console):
    items = list(core_progress.track(["a", "b"], "Letters"))
    assert items == ["a", "b"]


def test_task_inert_when_disabled(disabled_console):
    with core_progress.task("Silent work", total=10) as handle:
        handle.advance()
        handle.update(completed=5, description="renamed")


def test_task_advances(live_console):
    with core_progress.task("Visible work", total=4) as handle:
        for _ in range(4):
            handle.advance()


def test_no_progress_variable(live_console, monkeypatch):
    monkeypatch.setenv("HMP_NO_PROGRESS", "1")
    with core_progress.phase("Muted phase"):
        pass
    assert "✓" not in live_console.getvalue()


def test_quiet_mode(live_console):
    core_progress.set_console_mode("quiet")
    with core_progress.phase("Quiet phase"):
        pass
    assert "✓" not in live_console.getvalue()


def test_nested_phase_status_task(live_console):
    with core_progress.phase("Outer"):
        with core_progress.status("Inner status"):
            with core_progress.task("Inner bar", total=2) as handle:
                handle.advance(2)
    output = live_console.getvalue()
    assert "Outer" in output


def _handled(message: str, level: int = logging.INFO, **extra) -> str:
    handler = core_progress.ConsoleLogHandler()
    record = logging.LogRecord("hydromodpy.x", level, __file__, 1, message, None, None)
    record.__dict__.update(extra)
    handler.emit(record)
    return Text.from_ansi(core_progress.console.file.getvalue()).plain


@pytest.mark.parametrize(
    ("level", "glyph"),
    [
        (logging.DEBUG, "·"),
        (logging.INFO, "›"),
        (logging.WARNING, "!"),
        (logging.ERROR, "✗"),
        (logging.CRITICAL, "✗"),
    ],
)
def test_log_glyph(live_console, level, glyph):
    assert _handled("hello", level) == f"{glyph} hello\n"


def test_log_wrapping(live_console):
    text = _handled("word " * 60, logging.WARNING)
    lines = text.splitlines()
    assert len(lines) > 1
    assert lines[0].startswith("! word")
    assert all(line.startswith("  word") for line in lines[1:])
    assert all(len(line) <= 100 and not line.endswith(" ") for line in lines)


def test_log_hint(live_console):
    assert _handled("next: hmp show run", **core_progress.HINT) == ("  next: hmp show run\n")


def test_fmt_duration():
    assert core_progress._fmt_duration(3.21) == "3.2s"
    assert core_progress._fmt_duration(75) == "1m 15s"
    assert core_progress._fmt_duration(3700) == "1h 01m"


def test_suppressed_zone(live_console):
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append
    logger = get_logger("hydromodpy.core.console.progress")
    logger.addHandler(handler)
    try:
        with core_progress.suppressed():
            with core_progress.phase("Trial run"):
                pass
    finally:
        logger.removeHandler(handler)
    assert "✓" not in live_console.getvalue()
    assert all(r.levelno == logging.DEBUG for r in records)


def test_plain_handler_off_terminal(disabled_console):
    handler = core_progress.make_console_handler()
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, core_progress.ConsoleLogHandler)


def test_plain_handler_follows_stderr(disabled_console, monkeypatch):
    gone = io.StringIO()
    monkeypatch.setattr("sys.stderr", gone)
    handler = core_progress.make_console_handler()
    gone.close()
    current = io.StringIO()
    monkeypatch.setattr("sys.stderr", current)

    handler.handle(logging.makeLogRecord({"msg": "still shown", "levelno": logging.WARNING}))

    assert current.getvalue() == "still shown\n"


def test_plain_handler_survives_redirect(disabled_console, monkeypatch):
    pinned = io.StringIO()
    monkeypatch.setattr("sys.stderr", pinned)
    handler = core_progress.make_console_handler()
    with contextlib.redirect_stderr(io.StringIO()):
        handler.handle(logging.makeLogRecord({"msg": "not swallowed"}))

    assert pinned.getvalue() == "not swallowed\n"


def test_console_stream_pinned():
    module = importlib.import_module("hydromodpy.core.console.progress")
    before = module.console.file
    with contextlib.redirect_stderr(io.StringIO()):
        assert module.console.file is before


def test_child_process_is_silent(live_console, monkeypatch):
    monkeypatch.setattr(multiprocessing, "parent_process", lambda: object(), raising=True)
    with core_progress.phase("Child phase"):
        pass
    assert "✓" not in live_console.getvalue()


def _progress_records() -> tuple[logging.Handler, list[logging.LogRecord]]:
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append
    get_logger("hydromodpy.core.console.progress").addHandler(handler)
    return handler, records


def test_empty_bar_not_drawn(live_console):
    # No "Data families 0/0" bar when a run loads no data family.
    with core_progress.task("Data families", total=0) as handle:
        assert handle._progress is None
        assert core_progress._manager._progress is None
    assert "0/0" not in live_console.getvalue()


def test_empty_bar_logs_debug_only(disabled_console):
    handler, records = _progress_records()
    try:
        with core_progress.task("Data families", total=0):
            pass
    finally:
        get_logger("hydromodpy.core.console.progress").removeHandler(handler)
    assert records
    assert all(r.levelno == logging.DEBUG for r in records)


def test_bar_drawn(live_console):
    with core_progress.task("Data families", total=2) as handle:
        assert handle._progress is not None
        handle.advance(2)


def test_after_phase_below_checkmark(live_console):
    # The run recap belongs under the checkmark of the step that reports it.
    def recap() -> None:
        core_progress.console.print("Run completed: demo")

    with core_progress.phase("export"):
        core_progress.after_phase(recap)
        core_progress.console.print("inside the phase")
    output = live_console.getvalue()
    assert output.index("inside the phase") < output.index("✓")
    assert output.index("✓") < output.index("Run completed: demo")


def test_after_phase_innermost(live_console):
    seen: list[str] = []
    with core_progress.phase("calibration"):
        with core_progress.phase("export"):
            core_progress.after_phase(lambda: seen.append("recap"))
            assert seen == []
        assert seen == ["recap"]


def test_after_phase_outside():
    seen: list[str] = []
    core_progress.after_phase(lambda: seen.append("now"))
    assert seen == ["now"]


def test_after_phase_dropped_on_failure(live_console):
    seen: list[str] = []
    with pytest.raises(RuntimeError):
        with core_progress.phase("export"):
            core_progress.after_phase(lambda: seen.append("recap"))
            raise RuntimeError("packaging failed")
    assert seen == []
    # The stack is balanced again: a later call outside a phase runs at once.
    core_progress.after_phase(lambda: seen.append("later"))
    assert seen == ["later"]


def test_at_end_after_every_later_phase(live_console):
    # The run recap of the seal comes after the figures drawn by the next step.
    seen: list[str] = []
    with core_progress.held_to_end():
        with core_progress.phase("seal"):
            core_progress.at_end(lambda: seen.append("recap"))
        with core_progress.phase("display"):
            seen.append("figures")
        with core_progress.held_to_end():
            seen.append("nested")
        assert seen == ["figures", "nested"]
    assert seen == ["figures", "nested", "recap"]


def test_at_end_outside_a_hold_waits_for_the_phase(live_console):
    seen: list[str] = []
    with core_progress.phase("seal"):
        core_progress.at_end(lambda: seen.append("recap"))
        assert seen == []
    assert seen == ["recap"]


def test_at_end_dropped_on_failure(live_console):
    seen: list[str] = []
    with pytest.raises(RuntimeError):
        with core_progress.held_to_end():
            core_progress.at_end(lambda: seen.append("recap"))
            raise RuntimeError("a figure failed")
    assert seen == []
    core_progress.at_end(lambda: seen.append("later"))
    assert seen == ["later"]


def test_failing_deferred_line(live_console):
    def broken() -> None:
        raise ValueError("boom")

    seen: list[str] = []
    with core_progress.phase("export"):
        core_progress.after_phase(broken)
        core_progress.after_phase(lambda: seen.append("next"))
    assert seen == ["next"]
