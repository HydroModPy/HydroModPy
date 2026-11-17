"""The router of the package logger: each context writes its own files, no line crosses."""

from __future__ import annotations

import logging
from contextvars import copy_context

import pytest

import hydromodpy.core.logging as core_logging
from hydromodpy.core.logging import RUN_SINKS, LogManager, SinkRouter, get_logger

LOGGER = get_logger("hydromodpy.tests.router")


class Collector(logging.Handler):
    """A sink that keeps the messages it receives."""

    def __init__(self, level: int = logging.DEBUG) -> None:
        super().__init__(level=level)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.mark.parametrize(
    ("sink_level", "record_level", "arrives"),
    [
        pytest.param(logging.DEBUG, logging.DEBUG, True, id="a debug sink takes a debug line"),
        pytest.param(logging.WARNING, logging.INFO, False, id="a warning sink drops an info line"),
        pytest.param(logging.WARNING, logging.WARNING, True, id="a warning sink takes a warning"),
        pytest.param(logging.INFO, logging.ERROR, True, id="an info sink takes an error"),
    ],
)
def test_a_sink_keeps_its_own_level(sink_level: int, record_level: int, arrives: bool) -> None:
    sink = Collector(sink_level)

    def emit() -> None:
        RUN_SINKS.set((sink,))
        LOGGER.log(record_level, "one line")

    copy_context().run(emit)

    assert sink.messages == (["one line"] if arrives else [])


def test_the_manager_no_longer_opens_a_log_in_the_project() -> None:
    assert not hasattr(LogManager, "set_simulation_log")
    assert not hasattr(core_logging, "setup_simulation_log")


@pytest.fixture
def clean_logging(monkeypatch: pytest.MonkeyPatch):
    """Isolate the package logger, the root handlers and the manager singleton."""
    import warnings

    package = get_logger("hydromodpy")
    root = logging.root
    saved = (package.handlers[:], package.level, package.propagate, root.handlers[:])
    saved_show = warnings.showwarning
    monkeypatch.setattr(LogManager, "_instance", None)
    yield package
    package.handlers[:] = saved[0]
    package.setLevel(saved[1])
    package.propagate = saved[2]
    root.handlers[:] = saved[3]
    warnings.showwarning = saved_show
    core_logging.core_progress.set_console_mode(core_logging.DEFAULT_VERBOSITY)


def test_ensure_sink_router_reuses_the_installed_router(clean_logging: logging.Logger) -> None:
    clean_logging.addHandler(logging.NullHandler())
    first = core_logging.ensure_sink_router()
    assert core_logging.ensure_sink_router() is first
    assert sum(isinstance(h, SinkRouter) for h in clean_logging.handlers) == 1


def test_the_user_log_is_written_once_at_the_console_level(
    clean_logging: logging.Logger, tmp_path
) -> None:
    manager = LogManager(mode="verbose", log_dir=str(tmp_path / "logs"), overwrite=True)
    manager.set_console_level("verbose")
    get_logger("hydromodpy.tests.userlog").info("hello file")
    get_logger("hydromodpy.tests.userlog").debug("below the level")

    named = [h for h in clean_logging.handlers if h.get_name() == "user_log"]
    assert len(named) == 1
    named[0].flush()
    text = (tmp_path / "logs" / "hydromodpy.log").read_text(encoding="utf-8")
    assert "hello file" in text
    assert "below the level" not in text
    assert manager._has_user_log_handler()


def test_enable_user_log_defaults_to_the_current_directory(
    clean_logging: logging.Logger, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = LogManager(mode="quiet")
    assert not manager._has_user_log_handler()
    manager.enable_user_log()
    assert manager.log_dir == str(tmp_path)
    assert (tmp_path / "hydromodpy.log").exists()
    assert manager._has_user_log_handler()


@pytest.mark.parametrize(("show", "level"), [(True, logging.WARNING), (False, logging.CRITICAL)])
def test_show_library_logs_sets_the_level_of_third_party_loggers(
    clean_logging: logging.Logger, show: bool, level: int
) -> None:
    manager = LogManager(mode="quiet")
    manager.show_library_logs(show)
    assert manager.verbose_libraries is show
    assert logging.Logger.manager.getLogger("rasterio").level == level
    assert logging.Logger.manager.getLogger("shapely").level == level


def test_set_verbosity_creates_then_updates_the_manager(clean_logging: logging.Logger) -> None:
    assert LogManager._instance is None
    assert core_logging.current_verbosity() == core_logging.DEFAULT_VERBOSITY
    assert core_logging.set_verbosity("debug") == "debug"
    assert core_logging.current_verbosity() == "debug"
    assert core_logging.set_verbosity("quiet") == "quiet"
    assert core_logging.current_verbosity() == "quiet"


def test_a_held_console_returns_its_warnings_once(clean_logging: logging.Logger) -> None:
    held = core_logging.hold_console()
    assert LogManager._instance is not None
    assert held in clean_logging.handlers
    assert held in logging.root.handlers
    assert not any(type(h) is logging.StreamHandler for h in clean_logging.handlers)

    logger = get_logger("hydromodpy.tests.held")
    logger.info("too quiet")
    logger.warning("careful %s", "now")
    logger.warning("careful %s", "now")

    assert held.drain() == [("hydromodpy.tests.held", logging.WARNING, "careful now")]
    assert held.drain() == []


def test_print_held_replays_each_line_under_its_logger() -> None:
    sink = Collector()
    logger = get_logger("hydromodpy.tests.replay")
    logger.addHandler(sink)
    logger.setLevel(logging.DEBUG)
    try:
        core_logging.print_held([("hydromodpy.tests.replay", logging.WARNING, "100% sure")])
    finally:
        logger.removeHandler(sink)
    assert sink.messages == ["100% sure"]
