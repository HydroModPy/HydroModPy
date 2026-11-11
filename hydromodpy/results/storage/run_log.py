"""The logs of one attempt: ``<run>/logs/run.log``, the project debug log, and the tail an outcome carries.

Why
---
A failed case has to explain itself from its own directory. The outcome
names the error; the end of the log says what the run was doing when it
died. The attempt opens two files for its whole span and closes them on the
way out. ``<run>/logs/run.log`` holds what this run wrote.
``<project>/.hmp/logs/hydromodpy_debug.log`` holds what every run of the
project wrote, and records DEBUG whatever the console shows. A calibration
session, a spin-up and the build of a project's model write the project
debug log too, through :func:`project_log`. The outcome of a failed or
aborted attempt carries the last lines of ``run.log``, and the launcher
reads the same lines for a worker that died without writing.

How
---
Neither file is a handler of the package logger. The attempt adds both to
:data:`~hydromodpy.core.logging.RUN_SINKS`, the sinks of its own context, and
gives the previous value back on exit, so two runs in two threads of one
process write two ``run.log`` files and no line crosses. A thread pool that a
run starts submits its tasks through ``contextvars.copy_context().run``. A
context that already writes the project debug log does not open it twice, so
an attempt inside a calibration or a spin-up writes each line there once.

Format
------
One line per record, ``<instant> [<level>] [<logger>] [<module>:<line>] <message>``,
appended for the span of the attempt. A retry starts a new file: the
previous ``logs/`` directory is filed under ``attempts/<k>/`` by the claim.
The project debug log rotates when it is opened: past
:data:`PROJECT_LOG_MAX_BYTES` it becomes ``.1``, the old ``.1`` becomes ``.2``,
and so on to :data:`PROJECT_LOG_KEPT`. A rename that fails because another
run did it first is ignored.
"""

from __future__ import annotations

import functools
import logging
import os
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeVar, cast

from hydromodpy.core.logging import RUN_SINKS, ensure_sink_router, get_logger
from hydromodpy.core.state.layout import internal_dir
from hydromodpy.results.storage.contract import RUN_LOG_FILENAME, RUN_LOGS_DIRNAME

PACKAGE_LOGGER: Final[str] = "hydromodpy"
"""The logger every module of the package writes to."""

LOG_TAIL_LINES: Final[int] = 20
"""How many lines of the log an outcome carries."""

PROJECT_LOG_FILENAME: Final[str] = "hydromodpy_debug.log"
"""The project debug log, under ``<project>/.hmp/logs/``."""

PROJECT_LOG_MAX_BYTES: Final[int] = 8 * 1024 * 1024
"""Size at which the project debug log is rotated when an attempt opens it."""

PROJECT_LOG_KEPT: Final[int] = 3
"""Old project debug logs kept, ``hydromodpy_debug.log.1`` to ``.3``."""

_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"

_logger = get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class RunLogs:
    """The files an attempt writes and the sinks of the context before it opened them."""

    handlers: tuple[logging.Handler, ...]
    previous: tuple[logging.Handler, ...]


def run_log_path(run_dir: str | Path) -> Path:
    """Return ``<run>/logs/run.log``."""
    return Path(run_dir) / RUN_LOGS_DIRNAME / RUN_LOG_FILENAME


def project_log_path(project_root: str | Path) -> Path:
    """Return ``<project>/.hmp/logs/hydromodpy_debug.log``."""
    return internal_dir(Path(project_root)) / RUN_LOGS_DIRNAME / PROJECT_LOG_FILENAME


def rotate_project_log(path: Path) -> None:
    """Move *path* to ``.1`` and shift the older ones when it is past the size limit."""
    try:
        if path.stat().st_size <= PROJECT_LOG_MAX_BYTES:
            return
    except OSError:
        return
    for index in range(PROJECT_LOG_KEPT, 1, -1):
        _rename(path.with_name(f"{path.name}.{index - 1}"), path.with_name(f"{path.name}.{index}"))
    _rename(path, path.with_name(f"{path.name}.1"))


def _rename(source: Path, target: Path) -> None:
    try:
        os.replace(source, target)
    except OSError:
        # Another run rotated first, or the file is gone: nothing left to move.
        pass


def _file_handler(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FORMAT))
    return handler


def _project_sink(project_root: str | Path) -> logging.Handler | None:
    """Open the project debug log, or None when this context writes it already."""
    path = project_log_path(project_root)
    opened = os.path.abspath(path)
    if any(getattr(sink, "baseFilename", None) == opened for sink in RUN_SINKS.get()):
        return None
    try:
        rotate_project_log(path)
        return _file_handler(path)
    except OSError as exc:
        _logger.warning("The project log %s is not writable (%s); it is left out.", path, exc)
        return None


def attach_run_log(run_dir: str | Path, project_root: str | Path | None = None) -> RunLogs:
    """Start writing the package log into the run, and into the project log when it is named.

    The two files become sinks of the current context only. The result goes
    back to :func:`detach_run_log` on the same context.
    """
    ensure_sink_router()
    handlers = [_file_handler(run_log_path(run_dir))]
    project_sink = None if project_root is None else _project_sink(project_root)
    if project_sink is not None:
        handlers.append(project_sink)
    previous = RUN_SINKS.get()
    RUN_SINKS.set(previous + tuple(handlers))
    return RunLogs(tuple(handlers), previous)


def detach_run_log(logs: RunLogs) -> None:
    """Give the sinks of the context back and close the files."""
    RUN_SINKS.set(logs.previous)
    for handler in logs.handlers:
        handler.close()


@contextmanager
def project_log(project_root: str | Path) -> Iterator[None]:
    """Write the package log into the project debug log for the span of the block.

    The file is a sink of the current context only, like the logs of an
    attempt. A calibration session, a spin-up and the build of a model use it,
    so their lines reach the project log without a run directory.
    """
    ensure_sink_router()
    sink = _project_sink(project_root)
    logs = RunLogs(() if sink is None else (sink,), RUN_SINKS.get())
    RUN_SINKS.set(logs.previous + logs.handlers)
    try:
        yield
    finally:
        detach_run_log(logs)


def in_project_log(root_of: Callable[..., Path]) -> Callable[[_F], _F]:
    """Run the decorated call inside :func:`project_log`; ``root_of`` gets its arguments."""

    def decorate(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with project_log(root_of(*args, **kwargs)):
                return fn(*args, **kwargs)

        return cast(_F, wrapper)

    return decorate


def read_log_tail(run_dir: str | Path, lines: int = LOG_TAIL_LINES) -> list[str]:
    """Return the last *lines* lines of the run log, or nothing without a log."""
    path = run_log_path(run_dir)
    if not path.is_file():
        return []
    tail: deque[str] = deque(maxlen=lines)
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            tail.append(line.rstrip("\n"))
    return list(tail)


__all__ = [
    "LOG_TAIL_LINES",
    "PACKAGE_LOGGER",
    "PROJECT_LOG_FILENAME",
    "PROJECT_LOG_KEPT",
    "PROJECT_LOG_MAX_BYTES",
    "RunLogs",
    "attach_run_log",
    "detach_run_log",
    "in_project_log",
    "project_log",
    "project_log_path",
    "read_log_tail",
    "rotate_project_log",
    "run_log_path",
]
