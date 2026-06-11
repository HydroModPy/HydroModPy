"""Unit tests for the core progress system."""

from __future__ import annotations

import io
import logging

import pytest
from rich.console import Console

from hydromodpy.core import progress as core_progress
from hydromodpy.core.logging import get_logger


@pytest.fixture
def live_console(monkeypatch):
    """Force an interactive console writing into a StringIO buffer."""
    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=True, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    monkeypatch.delenv("HMP_NO_PROGRESS", raising=False)
    core_progress.set_console_mode("verbose")
    yield buffer
    core_progress.set_console_mode("verbose")


@pytest.fixture
def disabled_console(monkeypatch):
    """Force a non-interactive console (CI / piped output)."""
    buffer = io.StringIO()
    fake = Console(file=buffer, force_terminal=False, width=100)
    monkeypatch.setattr(core_progress, "console", fake)
    core_progress.set_console_mode("verbose")
    yield buffer


def test_phase_prints_checkmark_when_rendering(live_console):
    with core_progress.phase("Loading climate data"):
        pass
    output = live_console.getvalue()
    assert "✓" in output
    assert "Loading climate data" in output


def test_phase_prints_cross_on_failure(live_console):
    with pytest.raises(ValueError):
        with core_progress.phase("Broken step"):
            raise ValueError("boom")
    output = live_console.getvalue()
    assert "✗" in output
    assert "Broken step" in output


def test_phase_logs_info_when_disabled(disabled_console, caplog):
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append
    logger = get_logger("hydromodpy.core.progress")
    logger.addHandler(handler)
    try:
        with core_progress.phase("Plain phase"):
            pass
    finally:
        logger.removeHandler(handler)
    infos = [r for r in records if r.levelno == logging.INFO]
    assert any("Plain phase" in r.getMessage() for r in infos)
    assert disabled_console.getvalue() == ""


def test_track_yields_all_items_disabled(disabled_console):
    items = list(core_progress.track([1, 2, 3], "Counting"))
    assert items == [1, 2, 3]


def test_track_yields_all_items_rendering(live_console):
    items = list(core_progress.track(["a", "b"], "Letters"))
    assert items == ["a", "b"]


def test_task_handle_is_inert_when_disabled(disabled_console):
    with core_progress.task("Silent work", total=10) as handle:
        handle.advance()
        handle.update(completed=5, description="renamed")


def test_task_advances_when_rendering(live_console):
    with core_progress.task("Visible work", total=4) as handle:
        for _ in range(4):
            handle.advance()


def test_hmp_no_progress_disables_rendering(live_console, monkeypatch):
    monkeypatch.setenv("HMP_NO_PROGRESS", "1")
    with core_progress.phase("Muted phase"):
        pass
    assert "✓" not in live_console.getvalue()


def test_quiet_mode_disables_rendering(live_console):
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


def test_console_log_handler_prints_formatted_record(live_console):
    handler = core_progress.ConsoleLogHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    record = logging.LogRecord("hydromodpy.x", logging.INFO, __file__, 1, "hello", None, None)
    handler.emit(record)
    assert "[INFO] hello" in live_console.getvalue()


def test_fmt_duration():
    assert core_progress._fmt_duration(3.21) == "3.2s"
    assert core_progress._fmt_duration(75) == "1m 15s"
    assert core_progress._fmt_duration(3700) == "1h 01m"


def test_suppressed_zone_mutes_rendering_and_demotes_logs(live_console):
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append
    logger = get_logger("hydromodpy.core.progress")
    logger.addHandler(handler)
    try:
        with core_progress.suppressed():
            with core_progress.phase("Trial run"):
                pass
    finally:
        logger.removeHandler(handler)
    assert "✓" not in live_console.getvalue()
    assert all(r.levelno == logging.DEBUG for r in records)


def test_make_console_handler_plain_when_not_terminal(disabled_console):
    handler = core_progress.make_console_handler()
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, core_progress.ConsoleLogHandler)


def test_console_stream_pinned_against_redirect_stderr():
    import contextlib
    import importlib

    module = importlib.import_module("hydromodpy.core.progress")
    before = module.console.file
    with contextlib.redirect_stderr(io.StringIO()):
        assert module.console.file is before


def test_rendering_disabled_in_child_process(live_console, monkeypatch):
    import multiprocessing

    monkeypatch.setattr(multiprocessing, "parent_process", lambda: object(), raising=True)
    with core_progress.phase("Child phase"):
        pass
    assert "✓" not in live_console.getvalue()
