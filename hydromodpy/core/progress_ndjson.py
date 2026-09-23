"""NDJSON progress sink, independent of the rich console renderer.

``core.progress`` renders phases, statuses and tasks on a live console, and
``render_enabled()`` returns ``False`` for every process that is not attached
to a terminal (``HMP_NO_PROGRESS``, a non-verbose console mode, a
multiprocessing child, or stdio that is not a tty). That is exactly the case
of a capability running under an orchestrator, so today every progress update
it emits goes nowhere.

This module is a second observer of the same events, fed from the same call
sites (``phase``, ``status``, ``task`` and the :class:`~hydromodpy.core.
progress.TaskHandle` it hands back). It never reads the renderer's state and
the renderer never reads this module: each can change without the other
noticing. Writing is gated on two things:

- :data:`ENV_VAR` naming a destination file: unset, :func:`emit` is a no-op,
  at the cost of one ``os.environ.get`` per event.
- the caller passing ``suppressed=True``: a repeated inner run (a
  calibration trial, a sweep child) is muted on the console by
  ``core.progress.suppressed()``, and the sink honours the same flag so a
  calibration of thousands of trials does not write three lines per trial
  forever. The outer run (the calibration itself) is acquired outside the
  suppressed block and keeps emitting.

Set, one JSON object per line is appended and flushed immediately, so a
supervisor tailing the file sees a line as soon as it is written and a
killed process leaves no half-written line. The file handle is closed at
interpreter exit through :mod:`atexit`, so nothing is left open or
unflushed once the process is done.

Never stdout: a capability's stdout carries exactly one JSON document, the
final outcome, and nothing else.

Event shape: this module emits the contract of ``boundary-spec.md`` section
1.5 -- ``ts``, ``stage``, ``step``, ``of``, ``percent``, ``message`` -- plus
two fields the spec does not carry: ``task_id`` (groups every event of one
task, which several concurrent bars need and a bare stage name does not
give) and ``state`` (``started`` / ``progress`` / ``completed`` / ``failed``,
which ``percent`` alone cannot distinguish -- a task at 100% and a task that
just started both read 0 or ``None``). ``core.progress`` carries one
description string per event, not the two-level phase/stage-plus-detail
hierarchy the spec's own example suggests, so ``stage`` and ``message``
currently carry that same string; ``step``/``of`` are the task's raw
``completed``/``total`` and ``percent`` is derived from them.
"""

from __future__ import annotations

import atexit
import itertools
import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import TextIO

# core/logging.py imports core/progress.py, which imports this module: going
# through hydromodpy.core.logging.get_logger here would cycle back. Same
# exemption as core/progress.py, see pyproject.toml.
logger = logging.getLogger("hydromodpy.core.progress_ndjson")

ENV_VAR = "HMP_PROGRESS_FILE"
"""Names the NDJSON file. Unset means: no sink, emit() is a no-op."""

_lock = threading.Lock()
_ids = itertools.count(1)
_open_path: str | None = None
_open_handle: TextIO | None = None


def new_task_id() -> int:
    """A process-wide id, stable across every event of one task."""
    return next(_ids)


def _handle_for(path: str) -> TextIO:
    """Return the open append handle for *path*, reopening on a change.

    A capability chain runs several jobs in one process, one
    :data:`ENV_VAR` value per job, so the handle this module holds open must
    follow the path rather than being opened once for the life of the
    process.
    """
    global _open_path, _open_handle
    if _open_path != path:
        if _open_handle is not None:
            try:
                _open_handle.close()
            except OSError:
                pass
        _open_handle = open(path, "a", encoding="utf-8")
        _open_path = path
    return _open_handle


def _percent(completed: float | None, total: float | None) -> float | None:
    """Fraction of *total* done, or ``None`` when either side is unknown."""
    if completed is None or not total:
        return None
    return round(completed / total * 100, 1)


def emit(
    task_id: int,
    description: str,
    *,
    completed: float | None,
    total: float | None,
    state: str,
    suppressed: bool = False,
) -> None:
    """Append one progress event, or do nothing when no sink is configured.

    ``suppressed`` mirrors ``core.progress.suppressed()``: a repeated inner
    run (a calibration trial, a sweep child) sets it so its own events are
    dropped here exactly as they are muted on the console, while the outer
    run keeps writing.
    """
    if suppressed:
        return
    path = os.environ.get(ENV_VAR)
    if not path:
        return
    event = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "stage": description,
        "step": completed,
        "of": total,
        "percent": _percent(completed, total),
        "message": description,
        "task_id": task_id,
        "state": state,
    }
    line = json.dumps(event)
    try:
        with _lock:
            handle = _handle_for(path)
            handle.write(line + "\n")
            handle.flush()
    except OSError:
        # An observability sink must never break the work it observes: a
        # missing directory, a full disk or a permission error here would
        # otherwise propagate out of phase()/status()/task(), above the
        # caller's `with` block, and abort the real capability. Stay a
        # no-op for as long as the path is bad, exactly like the unset case.
        logger.debug("progress ndjson sink: failed to write to %s", path, exc_info=True)


def _close_at_exit() -> None:
    """Close the cached append handle, if one is open.

    Registered once, below, with :mod:`atexit`. Also called directly by
    tests: it is idempotent and safe with nothing open.
    """
    global _open_path, _open_handle
    with _lock:
        if _open_handle is not None:
            try:
                _open_handle.close()
            except OSError:
                pass
        _open_handle = None
        _open_path = None


atexit.register(_close_at_exit)


__all__ = ["ENV_VAR", "emit", "new_task_id"]
