"""Shared flopy run wrappers with stress-period progress bars.

Both MODFLOW backends parse the same ``Solving:  Stress period: N`` stdout
lines, so the callback factory and the run wrappers live here instead of
being duplicated per backend.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
from collections.abc import Callable, Generator
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any

from hydromodpy.core.console import progress
from hydromodpy.core.console.progress import TaskHandle
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

SOLVING_LINE_RE = re.compile(
    r"Solving:\s+Stress period:\s+(\d+)\s+Time step:\s+(\d+)",
    re.IGNORECASE,
)


def make_solving_line_callback(handle: TaskHandle, nper: int) -> Callable[[str], None]:
    """Return a flopy ``custom_print`` callback driving ``handle``.

    Parses ``Solving: Stress period: N`` stdout lines into monotonic bar
    updates and forwards every other non-empty line to the debug log. The bar
    moves by at least a thousandth of the run: a daily chronicle of 12 418
    periods writes 1 000 progress events to the launcher, not 12 418.
    """
    last_period = 0
    stride = max(1, -(-int(nper) // 1000))

    def callback(line: str) -> None:
        nonlocal last_period
        match = SOLVING_LINE_RE.search(line)
        if match:
            period = int(match.group(1))
            if period >= min(last_period + stride, int(nper)) and period > last_period:
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


FORTRAN_BUFFER_ENV = "FORT_BUFFERED"
"""The variable the Intel Fortran runtime reads at start to buffer what a program writes."""


def run_simulation_with_progress(
    sim: Any,
    nper: int,
    description: str = "Solving stress periods",
) -> tuple[bool, list[str]]:
    """Run a flopy MF6 simulation with a stress-period progress bar.

    The release binaries of MODFLOW 6 are built with Intel Fortran, which writes
    each record of a binary file without a buffer unless ``FORT_BUFFERED`` asks
    for one. A daily budget file takes tens of thousands of small writes per
    time step, and on Windows each one is a system call an antivirus may
    inspect: a model of 28 545 cells ran 6.7 s per day without the buffer and
    0.38 s with it, alone, on a local disk or eight at a time. The head,
    budget and binary observation files are the same byte for byte. The buffer
    garbles an observation CSV under MODFLOW 6.6, which is why HydroModPy
    writes its observations in binary, and a model that still writes one runs
    without the buffer. A value the user set wins.
    """
    from flopy.mbase import resolve_exe

    env = None
    if FORTRAN_BUFFER_ENV not in os.environ and not writes_text_observations(sim):
        env = {**os.environ, FORTRAN_BUFFER_ENV: "TRUE"}
    workspace = sim.simulation_data.mfpath.get_sim_path()
    command = [str(resolve_exe(sim.exe_name))]
    with progress.task(description, total=int(nper)) as handle:
        return run_executable(command, workspace, make_solving_line_callback(handle, nper), env)


def writes_text_observations(sim: Any) -> bool:
    """Whether an observation package of *sim* writes a CSV, which the buffer garbles.

    HydroModPy writes its observations in binary, so this guards a model built
    another way. It reads the ``BEGIN continuous`` lines of the written files.
    """
    workspace = Path(sim.simulation_data.mfpath.get_sim_path())
    for model in sim.model_dict.values():
        for package in model.packagelist:
            if package.package_type != "obs":
                continue
            try:
                text = (workspace / package.filename).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return True
            for line in text.splitlines():
                words = line.upper().split()
                if words[:2] == ["BEGIN", "CONTINUOUS"] and "BINARY" not in words:
                    return True
    return False


def run_executable(
    command: list[str],
    cwd: str | os.PathLike[str],
    on_line: Callable[[str], None],
    env: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Run a MODFLOW executable, hand each line of its output to *on_line*.

    The same loop as ``flopy.mbase.run_model``, with the environment of the
    process as an argument. Success is the ``normal termination`` line.
    """
    lines: list[str] = []
    success = False
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        success = success or "normal termination" in line.lower()
        on_line(line)
        lines.append(line)
    process.wait()
    return success, lines


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
    "FORTRAN_BUFFER_ENV",
    "make_solving_line_callback",
    "run_model_with_progress",
    "run_executable",
    "run_simulation_with_progress",
    "stdout_to_debug_log",
    "write_listing_status",
    "writes_text_observations",
]
