"""Make a termination signal unwind the stack instead of cutting it.

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
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class TerminationRequested(KeyboardInterrupt):
    """SIGTERM, raised so the stack unwinds.

    It inherits KeyboardInterrupt so every ``except KeyboardInterrupt`` that
    already treats an interruption as an abort treats this one the same way. The
    distinct type is what lets a caller say which signal it was.
    """


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


__all__ = ["TerminationRequested", "terminate_as_interrupt"]
