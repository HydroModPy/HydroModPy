"""A file lock taken with ``O_CREAT | O_EXCL``, held by one process on one host.

Three users. The product store takes it so a product is not built twice; there
correctness never depends on it, because a finished directory is renamed in one
step. The project index (``results/catalog/index_file.py``) and the ledger of a
``figures/`` or ``exports/`` directory (``results/ledger.py``) take it so two
writers never read the same file and drop each other's change.

The file carries ``{pid, host, created}``. A lock is stale when its holder died
on this host, or when it is older than ``stale_after_s``. A holder that works
longer than that calls :meth:`LockFile.renew` now and then, which dates the
file again. A file that does not read (empty, or JSON cut short) is stale once
it is older than :data:`TORN_AFTER_S`: taking the lock and writing its JSON
last a few microseconds, so such a file is the trace of a process that died in
between, or of an older release. A stale file is taken back in one step: it
is renamed aside, and removed only when the file moved is the one judged
stale (same inode and date). Any other file is put back. Before it writes, a
holder checks :meth:`LockFile.still_held`: the lock may have been taken back
meanwhile. The
launcher keeps a lease of another kind (``project/launch/lease.py``): that one
is never taken back on age alone, an operator forces it. This module takes no lock of the
operating system: the file alone is the lock, on every system.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from hydromodpy.core.state.scratch import process_is_alive

DEFAULT_STALE_AFTER_S = 6 * 3600.0
"""Age past which a lock is stale, even when its holder still runs."""

DEFAULT_WAIT_S = 120.0
"""How long ``acquire`` waits before giving up and returning False."""

TORN_AFTER_S: Final = 5.0
"""Age past which a lock file that does not read is stale."""

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
        self._mine: LockInfo | None = None
        self._inode: tuple[int, int] | None = None

    def read(self) -> LockInfo | None:
        """Return the holder, or ``None`` when the file is absent or half written."""
        try:
            return _parse(self.path.read_bytes())
        except OSError:
            return None

    def is_stale(self, info: LockInfo | None) -> bool:
        """Whether a lock may be taken back: its holder died, or it is too old.

        ``info`` is what :meth:`read` gave. ``None`` means the file is gone, or
        it does not read: it is stale then once older than :data:`TORN_AFTER_S`.
        """
        if info is None:
            try:
                age = time.time() - self.path.stat().st_mtime
            except FileNotFoundError:
                return True
            return age > TORN_AFTER_S
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
                if not self._take_back_if_stale():
                    return False
                continue
            info = LockInfo(os.getpid(), socket.gethostname(), time.time())
            stat = os.fstat(fd)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(info), handle)
            self._mine = info
            self._inode = (stat.st_dev, stat.st_ino)
            self.held = True
            return True
        return False

    def _take_back_if_stale(self) -> bool:
        """Remove the lock file when it is stale, in one step. True when it is gone.

        One process at a time takes a lock back: it holds the guard file
        ``<lock>.takeover``, created with ``O_EXCL``, and judges the lock again
        under it. The file is then renamed aside and removed only when it is the
        very file judged stale. Any other file goes back in place.
        """
        judged = self._look()
        if judged is None:
            return True
        if not self.is_stale(_parse(judged[1])):
            return False
        guard = self.path.with_name(f"{self.path.name}.takeover")
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            _clear_dead_guard(guard)
            return False
        try:
            if self._look() != judged:
                return False
            aside = self._move_aside()
            if aside is None:
                return True
            if (_identity(os.stat(aside)), aside.read_bytes()) == judged:
                aside.unlink(missing_ok=True)
                return True
            self._put_back(aside)
            return False
        finally:
            guard.unlink(missing_ok=True)

    def _look(self) -> tuple[tuple[int, int, int], bytes] | None:
        """The identity and bytes of the lock file, or None when it is gone."""
        try:
            stat = os.stat(self.path)
            return _identity(stat), self.path.read_bytes()
        except FileNotFoundError:
            return None

    def _move_aside(self) -> Path | None:
        """Rename the lock file to a name of its own, or return None when it is gone."""
        aside = self.path.with_name(f"{self.path.name}.aside-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        try:
            os.replace(self.path, aside)
        except FileNotFoundError:
            return None
        return aside

    def _put_back(self, aside: Path) -> None:
        """Put a file moved aside back in place, unless a new lock took its place."""
        try:
            os.link(aside, self.path)
        except FileExistsError:
            pass  # A newer lock holds the path: the file moved aside lost its turn.
        aside.unlink(missing_ok=True)

    def still_held(self) -> bool:
        """Whether the file still carries the pid, host and date this object wrote.

        False when the lock was never taken, was released, or was taken back
        by another process (or by another lock object of this process).
        """
        return self.held and self._mine is not None and self.read() == self._mine

    def renew(self) -> None:
        """Date the lock again, when this object still holds it.

        The JSON is written in place, into the very file this object created,
        so a lock taken back meanwhile is left to its new holder. A reader that
        sees it half written takes it for torn but young, so not stale.
        """
        if not self.still_held():
            return
        try:
            fd = os.open(self.path, os.O_RDWR)
        except FileNotFoundError:
            return
        try:
            stat = os.fstat(fd)
            if (stat.st_dev, stat.st_ino) != self._inode or not self._carries_mine(fd):
                return
            info = LockInfo(os.getpid(), socket.gethostname(), time.time())
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, json.dumps(asdict(info)).encode("utf-8"))
            self._mine = info
        finally:
            os.close(fd)

    def _carries_mine(self, fd: int) -> bool:
        """Whether the open lock file still reads as what this object wrote."""
        os.lseek(fd, 0, os.SEEK_SET)
        return _parse(os.read(fd, 4096)) == self._mine

    def release(self) -> None:
        """Remove the lock when this object still holds it, and nothing otherwise."""
        if self.still_held():
            aside = self._move_aside()
            if aside is not None:
                moved = os.stat(aside)
                mine = (moved.st_dev, moved.st_ino) == self._inode
                if mine and _parse(aside.read_bytes()) == self._mine:
                    aside.unlink(missing_ok=True)
                else:
                    self._put_back(aside)
        self.held = False
        self._mine = None
        self._inode = None

    def __enter__(self) -> LockFile:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _parse(raw: bytes) -> LockInfo | None:
    """The holder written in a lock file, or None when it does not read."""
    try:
        return LockInfo(**json.loads(raw))
    except (ValueError, TypeError):
        return None


def _clear_dead_guard(guard: Path) -> None:
    """Remove a takeover guard left by a process that died while it held it.

    A take-back holds the guard a few microseconds, so a guard older than
    :data:`TORN_AFTER_S` has no living owner.
    """
    try:
        if time.time() - guard.stat().st_mtime > TORN_AFTER_S:
            guard.unlink(missing_ok=True)
    except FileNotFoundError:
        return


def _identity(stat: os.stat_result) -> tuple[int, int, int]:
    """The device, inode and date of a file: what tells two lock files apart."""
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns)


__all__ = ["DEFAULT_STALE_AFTER_S", "DEFAULT_WAIT_S", "TORN_AFTER_S", "LockFile", "LockInfo"]
