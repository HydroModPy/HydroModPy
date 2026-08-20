"""Shared flopy run wrappers with stress-period progress bars.

Both MODFLOW backends parse the same ``Solving:  Stress period: N`` stdout
lines, so the callback factory and the run wrappers live here instead of
being duplicated per backend.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Callable, Generator
from contextlib import contextmanager, redirect_stdout
from typing import Any

from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import TaskHandle

logger = get_logger(__name__)

SOLVING_LINE_RE = re.compile(
    r"Solving:\s+Stress period:\s+(\d+)\s+Time step:\s+(\d+)",
    re.IGNORECASE,
)


def make_solving_line_callback(handle: TaskHandle, nper: int) -> Callable[[str], None]:
    """Return a flopy ``custom_print`` callback driving ``handle``.

    Parses ``Solving: Stress period: N`` stdout lines into monotonic bar
    updates and forwards every other non-empty line to the debug log.
    """
    last_period = 0

    def callback(line: str) -> None:
        nonlocal last_period
        match = SOLVING_LINE_RE.search(line)
        if match:
            period = int(match.group(1))
            if period > last_period:
                last_period = period
                handle.update(completed=min(period, int(nper)))
            return
        stripped = line.strip()
        if stripped:
            logger.debug("%s", stripped)

    return callback


def run_model_with_progress(
    exe_name: str | os.PathLike[str],
    namefile: str | None,
    model_ws: str | os.PathLike[str],
    nper: int,
    description: str = "Solving stress periods",
) -> tuple[bool, list[str]]:
    """Run a MODFLOW executable with a stress-period progress bar."""
    import flopy.mbase

    with progress.task(description, total=int(nper)) as handle:
        return flopy.mbase.run_model(
            exe_name,
            namefile,
            model_ws=model_ws,
            silent=False,
            report=True,
            custom_print=make_solving_line_callback(handle, nper),
        )


def run_simulation_with_progress(
    sim: Any,
    nper: int,
    description: str = "Solving stress periods",
) -> tuple[bool, list[str]]:
    """Run a flopy MF6 simulation with a stress-period progress bar."""
    with progress.task(description, total=int(nper)) as handle:
        return sim.run_simulation(
            silent=False,
            report=True,
            custom_print=make_solving_line_callback(handle, nper),
        )


class _DebugLineWriter(io.TextIOBase):
    """File-like sink forwarding complete lines to the debug log."""

    def __init__(self, on_line: Callable[[str], None] | None = None) -> None:
        self._buffer = ""
        self._on_line = on_line

    def _emit(self, line: str) -> None:
        logger.debug("%s", line)
        if self._on_line is not None:
            self._on_line(line)

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._emit(line.rstrip())
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._emit(self._buffer.rstrip())
        self._buffer = ""


@contextmanager
def stdout_to_debug_log(
    on_line: Callable[[str], None] | None = None,
) -> Generator[None, None, None]:
    """Forward stray stdout prints (flopy write listings) to the debug log."""
    writer = _DebugLineWriter(on_line)
    with redirect_stdout(writer):
        try:
            yield
        finally:
            writer.flush()


WRITING_LINE_RE = re.compile(r"^\s*writing\s+(.+?)\.*\s*$", re.IGNORECASE)


@contextmanager
def write_listing_status(
    description: str = "Writing MODFLOW 6 input files",
) -> Generator[None, None, None]:
    """Status spinner mirroring flopy's write listing live.

    Each captured ``writing package x...`` stdout line retitles the
    spinner with the item being written; the full listing lands in the
    debug log.
    """
    with progress.status(description) as handle:

        def on_line(line: str) -> None:
            match = WRITING_LINE_RE.match(line)
            if match:
                handle.update(description=f"{description}: {match.group(1)}")

        with stdout_to_debug_log(on_line):
            yield


__all__ = [
    "SOLVING_LINE_RE",
    "WRITING_LINE_RE",
    "make_solving_line_callback",
    "run_model_with_progress",
    "run_simulation_with_progress",
    "stdout_to_debug_log",
    "write_listing_status",
]
