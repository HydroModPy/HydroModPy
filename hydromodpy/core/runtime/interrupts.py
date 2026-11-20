"""Make a termination signal or a stop request unwind the stack instead of cutting it.

A long run closes its session in a ``finally``: the status, the outcome, the end
date. SIGINT reaches that block because Python raises KeyboardInterrupt for it.
SIGTERM does not: the default handler ends the process where it stands, so the
``finally`` never runs and the session stays ``running`` in the index with no
end date and no outcome. Every scheduler stop, every container stop and every
plain ``kill`` sends SIGTERM, so on anything but a laptop that is the common
case rather than the exception.

The context manager below installs a handler that raises for the duration of the
block and puts the previous one back on the way out, nesting included. Outside
the main thread it is a no-op, because ``signal.signal`` is main-thread only and
a worker must not crash on that.

A stop can also be asked without a signal, by a file: ``request_stop`` of
``results/storage/attempt.py`` writes ``.hmp/stop.json`` in the run or session
folder, and the loops of a run call ``raise_if_stop_requested`` between two
steps, two runs of a plan or two time steps. A server can then stop a run
without a process id that may be its own. ``StopRequested`` inherits
KeyboardInterrupt for the same reason ``TerminationRequested`` does.

``raise_if_stop_requested`` costs about two microseconds, so a loop may call it at every
time step. The writer of the flag is ``request_stop`` in ``results/storage/attempt.py``.
"""

from __future__ import annotations

import json
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

STOP_FLAG_SCHEMA = "hydromodpy.stop.v1"
"""The schema of a stop flag: ``{"schema", "at", "host"}``, ``at`` an ISO UTC instant."""


class TerminationRequested(KeyboardInterrupt):
    """SIGTERM, raised so the stack unwinds.

    It inherits KeyboardInterrupt so every ``except KeyboardInterrupt`` that
    already treats an interruption as an abort treats this one the same way. The
    distinct type is what lets a caller say which signal it was.
    """


class StopRequested(KeyboardInterrupt):
    """A stop asked through the flag of the run, raised so the stack unwinds.

    It inherits KeyboardInterrupt so every block that closes a run on a signal
    closes it on a stop too. The message says when the stop was asked.
    """


def raise_if_stop_requested(flag: Path | None) -> None:
    """Raise :class:`StopRequested` when the stop flag ``flag`` is on disk.

    ``None`` is a run that cannot be stopped this way, a calibration trial
    without a folder, and does nothing. An absent file does nothing. A flag
    that cannot be read still stops: the file is there, so someone asked.
    One check costs a ``stat``, about 2 microseconds.
    """
    if flag is None:
        return
    path = Path(flag)
    if not path.exists():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StopRequested(f"stop requested by {path}, an unreadable flag") from None
    at = document.get("at") if isinstance(document, dict) else None
    if not at:
        raise StopRequested(f"stop requested by {path}, a flag without a date")
    raise StopRequested(f"stop requested at {at}")


@contextmanager
def terminate_as_interrupt() -> Iterator[None]:
    """Raise :class:`TerminationRequested` on SIGTERM inside this block."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _raise(signum: int, frame: FrameType | None) -> None:
        del frame
        logger.warning("Received signal %s; unwinding so the run closes its session.", signum)
        raise TerminationRequested(f"signal {signum}")

    try:
        previous = signal.signal(signal.SIGTERM, _raise)
    except (OSError, ValueError):
        # A host that will not let this process install a handler still runs;
        # it just keeps the platform default.
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


__all__ = [
    "STOP_FLAG_SCHEMA",
    "StopRequested",
    "TerminationRequested",
    "raise_if_stop_requested",
    "terminate_as_interrupt",
]
