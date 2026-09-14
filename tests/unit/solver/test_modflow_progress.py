"""Stdout-parsing progress callback shared by the MODFLOW backends."""

from __future__ import annotations

import logging

import pytest

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.progress import (
    SOLVING_LINE_RE,
    WRITING_LINE_RE,
    make_solving_line_callback,
    stdout_to_debug_log,
    write_listing_status,
)

_LOGGER_NAME = "hydromodpy.solver.modflow_common.progress"


class _RecordingLogHandler(logging.Handler):
    """Capture records directly: the hydromodpy logger does not propagate."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_records():
    handler = _RecordingLogHandler()
    logger = get_logger(_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


class _RecordingHandle:
    """Stub TaskHandle recording every completed value it receives."""

    def __init__(self) -> None:
        self.completed: list[float] = []

    def update(
        self,
        *,
        completed: float | None = None,
        total: float | None = None,
        description: str | None = None,
    ) -> None:
        if completed is not None:
            self.completed.append(completed)

    def advance(self, step: float = 1.0) -> None:
        raise AssertionError("the callback must use update(), not advance()")


def test_regex_matches_mf6_and_nwt_solving_lines() -> None:
    mf6_line = "    Solving:  Stress period:     3    Time step:     1"
    nwt_line = " Solving:  Stress period:    12    Time step:     4    Groundwater-Flow Eqn."
    assert SOLVING_LINE_RE.search(mf6_line).group(1) == "3"
    assert SOLVING_LINE_RE.search(nwt_line).group(1) == "12"
    assert SOLVING_LINE_RE.search("SOLVING:  STRESS PERIOD:  2  TIME STEP:  1") is not None
    assert SOLVING_LINE_RE.search("Run end date and time: 2026/06/11") is None


def test_callback_advances_once_per_stress_period() -> None:
    handle = _RecordingHandle()
    callback = make_solving_line_callback(handle, nper=3)
    callback("    Solving:  Stress period:     1    Time step:     1")
    callback("    Solving:  Stress period:     1    Time step:     2")
    callback("    Solving:  Stress period:     2    Time step:     1")
    callback("    Solving:  Stress period:     3    Time step:     1")
    assert handle.completed == [1, 2, 3]


def test_callback_is_monotonic_and_clamped_to_nper() -> None:
    handle = _RecordingHandle()
    callback = make_solving_line_callback(handle, nper=2)
    callback("    Solving:  Stress period:     2    Time step:     1")
    callback("    Solving:  Stress period:     1    Time step:     1")
    callback("    Solving:  Stress period:     5    Time step:     1")
    assert handle.completed == [2, 2]


def test_callback_handles_nwt_line_format() -> None:
    handle = _RecordingHandle()
    callback = make_solving_line_callback(handle, nper=4)
    callback(" Solving:  Stress period:     1    Time step:     1    Groundwater-Flow Eqn.")
    callback(" Solving:  Stress period:     2    Time step:     1    Groundwater-Flow Eqn.")
    assert handle.completed == [1, 2]


def test_callback_forwards_noise_to_debug_log(log_records) -> None:
    handle = _RecordingHandle()
    callback = make_solving_line_callback(handle, nper=2)
    callback("MODFLOW 6 compiled Feb 12 2026")
    callback("    Solving:  Stress period:     1    Time step:     1")
    callback("Normal termination of simulation.")
    messages = [record.getMessage() for record in log_records]
    assert "MODFLOW 6 compiled Feb 12 2026" in messages
    assert "Normal termination of simulation." in messages
    assert not any("Stress period" in message for message in messages)
    assert handle.completed == [1]


def test_callback_skips_empty_lines(log_records) -> None:
    handle = _RecordingHandle()
    callback = make_solving_line_callback(handle, nper=1)
    callback("")
    callback("   ")
    callback("\n")
    assert log_records == []
    assert handle.completed == []


def test_writing_line_regex_extracts_items() -> None:
    cases = {
        "writing simulation...": "simulation",
        "  writing simulation tdis package...": "simulation tdis package",
        "  writing solution package ims_gwf...": "solution package ims_gwf",
        "    writing package sfr...": "package sfr",
        "    writing model name file...": "model name file",
    }
    for line, expected in cases.items():
        match = WRITING_LINE_RE.match(line)
        assert match is not None, line
        assert match.group(1) == expected
    assert WRITING_LINE_RE.match("INFORMATION: maxbound changed to 3328") is None


def test_stdout_to_debug_log_forwards_lines(log_records) -> None:
    seen: list[str] = []
    with stdout_to_debug_log(seen.append):
        print("writing simulation...")
        print("INFORMATION: maxbound changed")
        print("tail without newline", end="")
    assert seen == [
        "writing simulation...",
        "INFORMATION: maxbound changed",
        "tail without newline",
    ]
    messages = [record.getMessage() for record in log_records]
    assert messages == seen


def test_write_listing_status_runs_body() -> None:
    ran = False
    with write_listing_status("Writing test input files"):
        print("  writing package sfr...")
        ran = True
    assert ran
