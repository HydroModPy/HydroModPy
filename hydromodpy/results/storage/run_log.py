"""The log of one attempt: ``<run>/logs/run.log``, and the tail the outcome carries.

Why
---
A failed case has to explain itself from its own directory. The outcome
names the error; the end of the log says what the run was doing when it
died. The attempt attaches a file handler to the package logger for its
whole span, at DEBUG level, and detaches it on the way out. The outcome of
a failed or aborted attempt carries the last lines of that file, and the
launcher reads the same lines for a worker that died without writing.

Format
------
One line per record, ``<instant> [<level>] [<logger>] [<module>:<line>] <message>``,
appended for the span of the attempt. A retry starts a new file: the
previous ``logs/`` directory is filed under ``attempts/<k>/`` by the claim.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Final

from hydromodpy.core.logging import get_logger
from hydromodpy.results.storage.contract import RUN_LOG_FILENAME, RUN_LOGS_DIRNAME

PACKAGE_LOGGER: Final[str] = "hydromodpy"
"""The logger every module of the package writes to."""

LOG_TAIL_LINES: Final[int] = 20
"""How many lines of the log an outcome carries."""

_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"


def run_log_path(run_dir: str | Path) -> Path:
    """Return ``<run>/logs/run.log``."""
    return Path(run_dir) / RUN_LOGS_DIRNAME / RUN_LOG_FILENAME


def attach_run_log(run_dir: str | Path) -> logging.Handler:
    """Start writing the package log into the run and return the handler."""
    path = run_log_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FORMAT))
    get_logger(PACKAGE_LOGGER).addHandler(handler)
    return handler


def detach_run_log(handler: logging.Handler) -> None:
    """Stop writing into the run and close the file."""
    get_logger(PACKAGE_LOGGER).removeHandler(handler)
    handler.close()


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
    "attach_run_log",
    "detach_run_log",
    "read_log_tail",
    "run_log_path",
]
