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
