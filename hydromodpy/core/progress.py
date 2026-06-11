"""Live console progress for long-running operations.

Single canonical progress system for HydroModPy. Renders phase
checkmarks, spinner statuses, and progress bars on stderr through one
shared rich display. Detailed messages keep flowing to the DEBUG file
log. Falls back to plain log lines when the console is not interactive
(pipes, CI), when the console mode is not "verbose", or when
``HMP_NO_PROGRESS`` is set.

Vocabulary:

- ``phase``: a named top-level step. Shows a spinner while running and
  prints a permanent checkmark line with its duration when done.
- ``status``: a transient sub-operation spinner. Leaves no trace on the
  console once finished.
- ``task`` / ``track``: a progress bar over a known (or unknown) total,
  manually advanced or wrapping an iterable.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

logger = logging.getLogger("hydromodpy.core.progress")

# Pin the stream object: redirect_stderr() zones (e.g. Whitebox stdio
# silencing) must not freeze the live display or swallow log lines.
console = Console(file=sys.stderr)

_STATUS_COLUMNS = (
    SpinnerColumn(style="cyan"),
    TextColumn("{task.description}"),
    TimeElapsedColumn(),
)
_BAR_COLUMNS = (
    TextColumn("  {task.description}"),
    BarColumn(bar_width=30),
    MofNCompleteColumn(),
    TaskProgressColumn(),
    TimeRemainingColumn(),
)
_BYTES_COLUMNS = (
    TextColumn("  {task.description}"),
    BarColumn(bar_width=30),
    DownloadColumn(),
    TransferSpeedColumn(),
    TimeRemainingColumn(),
)


class _AdaptiveProgress(Progress):
    """Progress that renders different columns per task kind."""

    def get_renderables(self) -> Iterable[Table]:
        groups: dict[str, list] = {"status": [], "bar": [], "bytes": []}
        for task in self.tasks:
            groups[task.fields.get("hmp_kind", "bar")].append(task)
        for kind, columns in (
            ("status", _STATUS_COLUMNS),
            ("bar", _BAR_COLUMNS),
            ("bytes", _BYTES_COLUMNS),
        ):
            if groups[kind]:
                self.columns = columns
                yield self.make_tasks_table(groups[kind])


class TaskHandle:
    """Handle on a live progress task. Inert when rendering is off."""

    def __init__(self, progress: Progress | None, task_id: TaskID | None) -> None:
        self._progress = progress
        self._task_id = task_id

    def advance(self, step: float = 1.0) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.advance(self._task_id, step)

    def update(
        self,
        *,
        completed: float | None = None,
        total: float | None = None,
        description: str | None = None,
    ) -> None:
        if self._progress is None or self._task_id is None:
            return
        kwargs: dict = {}
        if completed is not None:
            kwargs["completed"] = completed
        if total is not None:
            kwargs["total"] = total
        if description is not None:
            kwargs["description"] = description
        if kwargs:
            self._progress.update(self._task_id, **kwargs)

    def log(self, message: str) -> None:
        logger.debug("%s", message)


_NULL_HANDLE = TaskHandle(None, None)


class _ProgressManager:
    """Owns the single live display shared by all progress primitives."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._progress: _AdaptiveProgress | None = None
        self._active = 0
        self._console_mode = "verbose"

    def set_console_mode(self, mode: str) -> None:
        self._console_mode = mode

    def render_enabled(self) -> bool:
        if _is_suppressed():
            return False
        if os.environ.get("HMP_NO_PROGRESS"):
            return False
        if self._console_mode != "verbose":
            return False
        # Only the main process may drive the shared terminal display.
        if multiprocessing.parent_process() is not None:
            return False
        return console.is_terminal or console.is_jupyter

    def acquire(self, description: str, total: float | None, kind: str) -> TaskHandle:
        with self._lock:
            if not self.render_enabled():
                return _NULL_HANDLE
            if self._progress is None:
                self._progress = _AdaptiveProgress(
                    console=console,
                    transient=True,
                    refresh_per_second=10,
                )
                self._progress.start()
            self._active += 1
            task_id = self._progress.add_task(description, total=total, hmp_kind=kind)
            return TaskHandle(self._progress, task_id)

    def release(self, handle: TaskHandle) -> None:
        if handle._progress is None:
            return
        with self._lock:
            if self._progress is None:
                return
            self._progress.remove_task(handle._task_id)
            self._active -= 1
            if self._active <= 0:
                self._progress.stop()
                self._progress = None
                self._active = 0


_manager = _ProgressManager()

_suppress = threading.local()


def _is_suppressed() -> bool:
    return getattr(_suppress, "depth", 0) > 0


@contextmanager
def suppressed() -> Generator[None, None, None]:
    """Mute rendering and demote start logs to DEBUG in this thread.

    Used by repeated inner runs (calibration trials, sweep children)
    so they do not flood the console with per-run phase lines.
    """
    _suppress.depth = getattr(_suppress, "depth", 0) + 1
    try:
        yield
    finally:
        _suppress.depth -= 1


def set_console_mode(mode: str) -> None:
    """Sync the rendering policy with the LogManager console mode."""
    _manager.set_console_mode(mode)


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


@contextmanager
def phase(description: str) -> Generator[TaskHandle, None, None]:
    """Top-level step: live spinner, permanent checkmark line when done."""
    rendering = _manager.render_enabled()
    if rendering or _is_suppressed():
        logger.debug("phase start: %s", description)
    else:
        logger.info("%s", description)
    handle = _manager.acquire(description, None, "status")
    t0 = time.perf_counter()
    try:
        yield handle
    except BaseException:
        _manager.release(handle)
        if rendering:
            console.print(
                f"[red]✗[/red] {description} [dim]({_fmt_duration(time.perf_counter() - t0)})[/dim]"
            )
        logger.debug("phase failed: %s (%.1fs)", description, time.perf_counter() - t0)
        raise
    dt = time.perf_counter() - t0
    _manager.release(handle)
    if rendering:
        console.print(f"[green]✓[/green] {description} [dim]({_fmt_duration(dt)})[/dim]")
    logger.debug("phase done: %s (%.1fs)", description, dt)


@contextmanager
def status(description: str) -> Generator[TaskHandle, None, None]:
    """Transient sub-operation spinner. Leaves no console trace."""
    if not _manager.render_enabled():
        logger.debug("%s", description)
    handle = _manager.acquire(description, None, "status")
    t0 = time.perf_counter()
    try:
        yield handle
    finally:
        _manager.release(handle)
        logger.debug("done: %s (%.1fs)", description, time.perf_counter() - t0)


@contextmanager
def task(
    description: str,
    *,
    total: float | None = None,
    unit: str = "it",
) -> Generator[TaskHandle, None, None]:
    """Manually advanced progress bar. ``unit="bytes"`` renders sizes."""
    if not _manager.render_enabled():
        if _is_suppressed():
            logger.debug("%s", description)
        else:
            logger.info("%s", description)
    kind = "bytes" if unit == "bytes" else "bar"
    handle = _manager.acquire(description, total, kind)
    t0 = time.perf_counter()
    try:
        yield handle
    finally:
        _manager.release(handle)
        logger.debug("done: %s (%.1fs)", description, time.perf_counter() - t0)


def track(
    iterable: Iterable,
    description: str,
    *,
    total: float | None = None,
) -> Iterator:
    """Iterate with a progress bar."""
    if total is None and hasattr(iterable, "__len__"):
        total = len(iterable)
    with task(description, total=total) as handle:
        for item in iterable:
            yield item
            handle.advance()


class ConsoleLogHandler(logging.Handler):
    """Logging handler that prints through the shared rich console.

    Routing log lines through the console keeps them from corrupting
    the live progress display: rich renders them above the live area.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            console.print(self.format(record), markup=False, highlight=False, soft_wrap=True)
        except Exception:
            self.handleError(record)


def make_console_handler() -> logging.Handler:
    """Console handler for the LogManager: rich-aware on a terminal."""
    if console.is_terminal or console.is_jupyter:
        return ConsoleLogHandler()
    return logging.StreamHandler(sys.stderr)


__all__ = [
    "ConsoleLogHandler",
    "TaskHandle",
    "console",
    "make_console_handler",
    "phase",
    "set_console_mode",
    "status",
    "suppressed",
    "task",
    "track",
]
