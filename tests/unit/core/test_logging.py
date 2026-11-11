"""The router of the package logger: each context writes its own files, no line crosses."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

import hydromodpy.core.logging as core_logging
from hydromodpy.core.logging import (
    RUN_SINKS,
    LogManager,
    SinkRouter,
    ensure_sink_router,
    get_logger,
)

LOGGER = get_logger("hydromodpy.tests.router")


class Collector(logging.Handler):
    """A sink that keeps the messages it receives."""

    def __init__(self, level: int = logging.DEBUG) -> None:
        super().__init__(level=level)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _routers() -> list[logging.Handler]:
    return [h for h in get_logger("hydromodpy").handlers if isinstance(h, SinkRouter)]


def _write_lines(sink: Collector, label: str, count: int) -> None:
    """Emit *count* lines with *sink* as the only sink of this context."""
    RUN_SINKS.set((sink,))
    for index in range(count):
        LOGGER.debug("%s %d", label, index)


def test_the_package_logger_holds_one_router() -> None:
    first = ensure_sink_router()
    assert ensure_sink_router() is first
    LogManager(mode="normal")
    LogManager(mode="quiet")
    LogManager(mode="normal")
    assert _routers() == [first]


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


def test_a_context_writes_nothing_until_it_sets_sinks_and_leaves_the_caller_alone() -> None:
    sink = Collector()

    def emit() -> None:
        LOGGER.debug("before")
        RUN_SINKS.set((sink,))
        LOGGER.debug("inside")

    copy_context().run(emit)

    assert RUN_SINKS.get() == ()
    assert sink.messages == ["inside"]


def test_two_threads_fill_two_sinks_and_no_line_crosses() -> None:
    sinks = {"alpha": Collector(), "beta": Collector()}
    threads = [
        threading.Thread(target=_write_lines, args=(sink, label, 250))
        for label, sink in sinks.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    for label, sink in sinks.items():
        assert sink.messages == [f"{label} {index}" for index in range(250)]


@pytest.mark.parametrize(
    ("enters_a_copy", "lines_in_the_sink"),
    [
        pytest.param(True, 50, id="a task entered through copy_context keeps the sinks"),
        pytest.param(False, 0, id="a task submitted bare loses them"),
    ],
)
def test_a_pool_task_keeps_the_sinks_only_through_a_copy_of_the_context(
    enters_a_copy: bool, lines_in_the_sink: int
) -> None:
    sink = Collector()

    def task(index: int) -> None:
        LOGGER.debug("task %d", index)

    def run_pool() -> None:
        RUN_SINKS.set((sink,))
        with ThreadPoolExecutor(4) as pool:
            if enters_a_copy:
                futures = [pool.submit(copy_context().run, task, i) for i in range(50)]
            else:
                futures = [pool.submit(task, i) for i in range(50)]
            for future in futures:
                future.result(timeout=30)

    caller = threading.Thread(target=run_pool)
    caller.start()
    caller.join(timeout=60)

    assert len(sink.messages) == lines_in_the_sink


def test_the_manager_no_longer_opens_a_log_in_the_project() -> None:
    assert not hasattr(LogManager, "set_simulation_log")
    assert not hasattr(core_logging, "setup_simulation_log")


def test_emitting_adds_and_removes_no_handler() -> None:
    logger = get_logger("hydromodpy")
    before = list(logger.handlers)

    sink = Collector()
    copy_context().run(_write_lines, sink, "alpha", 5)

    assert list(logger.handlers) == before
    assert len(sink.messages) == 5
