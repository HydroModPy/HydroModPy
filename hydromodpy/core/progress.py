"""Live console progress for long-running operations.

Single canonical progress system for HydroModPy. Renders phase
checkmarks, spinner statuses, and progress bars on stderr through one
shared rich display. Detailed messages keep flowing to the DEBUG file
log. Falls back to plain log lines when the console is not interactive
(pipes, CI), when the verbosity leaves no room for it ("quiet" prints
nothing, "debug" scrolls plain lines instead), or when
``HMP_NO_PROGRESS`` is set.

Vocabulary:

- ``phase``: a named top-level step. Shows a spinner while running and
  prints a permanent checkmark line with its duration when done.
- ``status``: a transient sub-operation spinner. Leaves no trace on the
  console once finished.
- ``task`` / ``track``: a progress bar over a known (or unknown) total,
  manually advanced or wrapping an iterable. A bar over zero items has
  nothing to show and is never drawn.
- ``after_phase``: a line a step prints about its own outcome, held back
  until the phase has printed its checkmark.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time
from collections.abc import Callable, Generator, Iterable, Iterator
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
from rich.text import Text

from hydromodpy.core import progress_ndjson

logger = logging.getLogger("hydromodpy.core.progress")

MILESTONE_KEY = "hmp_milestone"
"""Record attribute marking a log line the default verbosity keeps."""

MILESTONE: dict[str, bool] = {MILESTONE_KEY: True}
"""``extra=`` payload for a milestone. Lives here, not in ``core.logging``,
because ``core.logging`` imports this module and the reverse would cycle."""

HINT_KEY = "hmp_hint"
"""Record attribute marking a milestone that only suggests what to do next."""

HINT: dict[str, bool] = {MILESTONE_KEY: True, HINT_KEY: True}
"""``extra=`` payload for a hint: a milestone the terminal prints dim, without a glyph."""

# Verbosity levels that still draw the live display. "quiet" has nothing to
# show and "debug" wants scrolling lines it can copy out of a pipe.
_RENDERING_MODES = ("normal", "verbose")

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
    """Handle on a live progress task. Inert when rendering is off.

    Rendering and the NDJSON sink (:mod:`hydromodpy.core.progress_ndjson`)
    are two independent observers of the same calls: rendering is skipped
    when ``progress`` is ``None``, and the NDJSON event is emitted unless
    the task was acquired under :func:`suppressed` (``progress_ndjson.emit``
    itself also no-ops without a configured sink), so a capability run with
    no terminal still gets a full event stream, and a suppressed inner run
    (a calibration trial, a sweep child) does not flood it.
    """

    def __init__(
        self,
        progress: Progress | None,
        task_id: TaskID | None,
        *,
        ndjson_id: int,
        description: str,
        total: float | None = None,
        suppressed: bool = False,
    ) -> None:
        self._progress = progress
        self._task_id = task_id
        self._ndjson_id = ndjson_id
        self._description = description
        self._total = total
        self._completed: float | None = 0.0 if total is not None else None
        self._suppressed = suppressed

    def advance(self, step: float = 1.0) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.advance(self._task_id, step)
        self._completed = (self._completed or 0.0) + step
        progress_ndjson.emit(
            self._ndjson_id,
            self._description,
            completed=self._completed,
            total=self._total,
            state="progress",
            suppressed=self._suppressed,
        )

    def update(
        self,
        *,
        completed: float | None = None,
        total: float | None = None,
        description: str | None = None,
    ) -> None:
        if completed is not None:
            self._completed = completed
        if total is not None:
            self._total = total
        if description is not None:
            self._description = description
        if self._progress is not None and self._task_id is not None:
            kwargs: dict = {}
            if completed is not None:
                kwargs["completed"] = completed
            if total is not None:
                kwargs["total"] = total
            if description is not None:
                kwargs["description"] = description
            if kwargs:
                self._progress.update(self._task_id, **kwargs)
        progress_ndjson.emit(
            self._ndjson_id,
            self._description,
            completed=self._completed,
            total=self._total,
            state="progress",
            suppressed=self._suppressed,
        )


class _ProgressManager:
    """Owns the single live display shared by all progress primitives."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._progress: _AdaptiveProgress | None = None
        self._active = 0
        self._console_mode = "normal"

    def set_console_mode(self, mode: str) -> None:
        self._console_mode = mode

    def render_enabled(self) -> bool:
        if _is_suppressed():
            return False
        if os.environ.get("HMP_NO_PROGRESS"):
            return False
        if self._console_mode not in _RENDERING_MODES:
            return False
        # Only the main process may drive the shared terminal display.
        if multiprocessing.parent_process() is not None:
            return False
        return console.is_terminal or console.is_jupyter

    def acquire(
        self, description: str, total: float | None, kind: str, *, render: bool = True
    ) -> TaskHandle:
        # Assigned and emitted unconditionally (modulo suppression): the
        # NDJSON sink is fed whether or not rendering is enabled, which is
        # the one case (no terminal) that matters to it. Suppression is
        # read once, here, and carried on the handle for its whole life --
        # exactly like render_enabled() below, so an outer task started
        # before a suppressed() block keeps emitting through it.
        ndjson_id = progress_ndjson.new_task_id()
        task_suppressed = _is_suppressed()
        progress_ndjson.emit(
            ndjson_id,
            description,
            completed=0.0 if total is not None else None,
            total=total,
            state="started",
            suppressed=task_suppressed,
        )
        with self._lock:
            if not render or not self.render_enabled():
                return TaskHandle(
                    None,
                    None,
                    ndjson_id=ndjson_id,
                    description=description,
                    total=total,
                    suppressed=task_suppressed,
                )
            if self._progress is None:
                self._progress = _AdaptiveProgress(
                    console=console,
                    transient=True,
                    refresh_per_second=10,
                )
                self._progress.start()
            self._active += 1
            task_id = self._progress.add_task(description, total=total, hmp_kind=kind)
            return TaskHandle(
                self._progress,
                task_id,
                ndjson_id=ndjson_id,
                description=description,
                total=total,
                suppressed=task_suppressed,
            )

    def release(self, handle: TaskHandle, *, state: str = "completed") -> None:
        if handle._progress is not None:
            with self._lock:
                if self._progress is not None:
                    self._progress.remove_task(handle._task_id)
                    self._active -= 1
                    if self._active <= 0:
                        self._progress.stop()
                        self._progress = None
                        self._active = 0
        progress_ndjson.emit(
            handle._ndjson_id,
            handle._description,
            completed=handle._completed,
            total=handle._total,
            state=state,
            suppressed=handle._suppressed,
        )


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


# One list of deferred callbacks per open phase, innermost last.
_open_phases = threading.local()


def _phase_stack() -> list[list[Callable[[], None]]]:
    stack = getattr(_open_phases, "stack", None)
    if stack is None:
        stack = []
        _open_phases.stack = stack
    return stack


def after_phase(callback: Callable[[], None]) -> None:
    """Run ``callback`` once the innermost open phase has printed its checkmark.

    A step that reports its own outcome, like the run recap, would otherwise
    print above its own checkmark and before its last work is done. Outside
    any phase the callback runs at once. When the phase fails the callback
    is dropped: the error is what the console must end on.
    """
    stack = _phase_stack()
    if stack:
        stack[-1].append(callback)
    else:
        callback()


def _run_deferred(callbacks: list[Callable[[], None]]) -> None:
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001 - a report line must never fail a run
            logger.debug("deferred phase callback failed", exc_info=True)


@contextmanager
def phase(description: str) -> Generator[TaskHandle, None, None]:
    """Top-level step: live spinner, permanent checkmark line when done."""
    rendering = _manager.render_enabled()
    if rendering or _is_suppressed():
        logger.debug("phase start: %s", description)
    else:
        # A milestone: without the live display these lines are the only
        # trace that the run is advancing, so the default verbosity keeps
        # them even though it drops ordinary INFO.
        logger.info("%s", description, extra=MILESTONE)
    handle = _manager.acquire(description, None, "status")
    stack = _phase_stack()
    stack.append([])
    t0 = time.perf_counter()
    try:
        yield handle
    except BaseException:
        dropped = stack.pop()
        _manager.release(handle, state="failed")
        if rendering:
            console.print(
                f"[red]✗[/red] {description} [dim]({_fmt_duration(time.perf_counter() - t0)})[/dim]"
            )
        logger.debug(
            "phase failed: %s (%.1fs), %d deferred line(s) dropped",
            description,
            time.perf_counter() - t0,
            len(dropped),
        )
        raise
    deferred = stack.pop()
    dt = time.perf_counter() - t0
    _manager.release(handle)
    if rendering:
        console.print(f"[green]✓[/green] {description} [dim]({_fmt_duration(dt)})[/dim]")
    logger.debug("phase done: %s (%.1fs)", description, dt)
    _run_deferred(deferred)


@contextmanager
def status(description: str) -> Generator[TaskHandle, None, None]:
    """Transient sub-operation spinner. Leaves no console trace."""
    if not _manager.render_enabled():
        logger.debug("%s", description)
    handle = _manager.acquire(description, None, "status")
    t0 = time.perf_counter()
    try:
        yield handle
    except BaseException:
        _manager.release(handle, state="failed")
        raise
    else:
        _manager.release(handle)
    finally:
        logger.debug("done: %s (%.1fs)", description, time.perf_counter() - t0)


@contextmanager
def task(
    description: str,
    *,
    total: float | None = None,
    unit: str = "it",
) -> Generator[TaskHandle, None, None]:
    """Manually advanced progress bar. ``unit="bytes"`` renders sizes.

    A total of zero means there is nothing to do: the bar is not drawn and
    the start is logged at DEBUG only, so no "0/0" line reaches the console.
    """
    empty = total == 0
    if not _manager.render_enabled() or empty:
        if _is_suppressed() or empty:
            logger.debug("%s", description)
        else:
            logger.info("%s", description)
    kind = "bytes" if unit == "bytes" else "bar"
    handle = _manager.acquire(description, total, kind, render=not empty)
    t0 = time.perf_counter()
    try:
        yield handle
    except BaseException:
        _manager.release(handle, state="failed")
        raise
    else:
        _manager.release(handle)
    finally:
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


# Level glyphs of a console log line, highest floor first. Same grammar as
# the phase checkmarks, so a warning reads like a step, not like a log dump.
_LEVEL_GLYPHS = (
    (logging.ERROR, "✗", "bold red"),
    (logging.WARNING, "!", "bold yellow"),
    (logging.INFO, "›", "cyan"),
    (logging.NOTSET, "·", "dim"),
)


def _glyph_line(record: logging.LogRecord, message: str, width: int) -> Text:
    """Render ``<glyph> <message>``, wrapped under the message's first character."""
    if getattr(record, HINT_KEY, False):
        glyph, glyph_style, text_style = " ", "", "dim"
    else:
        glyph, glyph_style = next(
            (mark, style) for floor, mark, style in _LEVEL_GLYPHS if record.levelno >= floor
        )
        text_style = ""
    line = Text()
    for index, part in enumerate(Text(message).wrap(console, max(width - 2, 20))):
        if index == 0:
            line.append(glyph, style=glyph_style)
            line.append(" ")
        else:
            line.append("\n  ")
        line.append(part.plain.rstrip(), style=text_style)
    return line


class ConsoleLogHandler(logging.Handler):
    """Logging handler that prints through the shared rich console.

    Routing log lines through the console keeps them from corrupting
    the live progress display: rich renders them above the live area.
    The level is a glyph in front of the message, so the formatter
    should not print it again.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            console.print(_glyph_line(record, self.format(record), console.width), soft_wrap=True)
        except Exception:
            self.handleError(record)


def make_console_handler() -> logging.Handler:
    """Console handler for the LogManager: rich-aware on a terminal."""
    if console.is_terminal or console.is_jupyter:
        return ConsoleLogHandler()
    return logging.StreamHandler(sys.stderr)


__all__ = [
    "HINT",
    "HINT_KEY",
    "MILESTONE",
    "MILESTONE_KEY",
    "ConsoleLogHandler",
    "TaskHandle",
    "after_phase",
    "console",
    "make_console_handler",
    "phase",
    "set_console_mode",
    "status",
    "suppressed",
    "task",
    "track",
]
