"""A file lock taken with ``O_CREAT | O_EXCL``, held by one process on one host.

The lock only avoids building the same product twice. Correctness never depends
on it: whoever writes renames a finished directory atomically, so a process that
built without the lock still leaves one complete product.

The file carries ``{pid, host, created}``. A lock is stale when its holder died
on this host, or when it is older than ``stale_after_s``. The launcher keeps a
lease of another kind (``project/launch/lease.py``): that one is never taken
back on age alone, an operator forces it. This module never calls ``fcntl``.
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from hydromodpy.core.state.scratch import process_is_alive

DEFAULT_STALE_AFTER_S = 6 * 3600.0
"""Age past which a lock is stale, even when its holder still runs."""

DEFAULT_WAIT_S = 120.0
"""How long ``acquire`` waits before giving up and returning False."""

_POLL_S = 0.02
"""Sleep between two attempts, so an idle wait burns nothing."""


@dataclass(frozen=True, slots=True)
class LockInfo:
    """Who took the lock, where and when (epoch seconds)."""

    pid: int
    host: str
    created: float


class LockFile:
    """Exclusive lock on a path, taken with ``O_CREAT | O_EXCL``."""

    def __init__(
        self,
        path: Path | str,
        *,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        wait_s: float = DEFAULT_WAIT_S,
    ) -> None:
        self.path = Path(path)
        self.stale_after_s = stale_after_s
        self.wait_s = wait_s
        self.held = False

    def read(self) -> LockInfo | None:
        """Return the holder, or ``None`` when the file is absent or half written."""
        try:
            return LockInfo(**json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, ValueError, TypeError, OSError):
            return None

    def is_stale(self, info: LockInfo | None) -> bool:
        """Whether a lock may be taken back: its holder died, or it is too old."""
        if info is None:
            return False
        if time.time() - info.created > self.stale_after_s:
            return True
        return info.host == socket.gethostname() and not process_is_alive(info.pid)

    def acquire(self) -> bool:
        """Take the lock, waiting up to ``wait_s``. Return False past it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_s
        while not self._try_acquire():
            if time.monotonic() > deadline:
                return False
            time.sleep(_POLL_S)
        return True

    def _try_acquire(self) -> bool:
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if not self.is_stale(self.read()):
                    return False
                self.path.unlink(missing_ok=True)
                continue
            info = LockInfo(os.getpid(), socket.gethostname(), time.time())
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(info), handle)
            self.held = True
            return True
        return False

    def release(self) -> None:
        """Remove the lock when this process still owns it, and nothing otherwise."""
        info = self.read()
        if self.held and info is not None and info.pid == os.getpid():
            self.path.unlink(missing_ok=True)
        self.held = False

    def __enter__(self) -> LockFile:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


__all__ = ["DEFAULT_STALE_AFTER_S", "DEFAULT_WAIT_S", "LockFile", "LockInfo"]
