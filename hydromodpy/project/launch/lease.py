"""The lease of the launcher: one launcher per project at a time.

Why
---
Two launchers on one project would start the same case twice and write the
same files of the shared data folder at the same moment. The first act
of a launcher is to take ``<project>/.hmp/launcher.lease`` with
``O_CREAT | O_EXCL``: the file names its host, its process and the instant.
A second launcher reads it and stops with that host and that process.

A lease left by a dead launcher is taken over by the rule of death of the
attempt protocol: same host and process gone. A lease of another host, or of
a process that still runs, is taken over only when the operator says the
holder is dead (``force``). A takeover moves the old lease aside atomically
and reads it again before removing it, so two launchers taking over the same
dead lease never both hold the project. The lease lives under ``.hmp/``: it is rebuilt
from nothing, a deleted lease only means no launcher holds the project.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.core.exceptions import WriteConflictError
from hydromodpy.core.io.document_version import TRANSIENT_REMEDY, check_document
from hydromodpy.core.io.filesystem import link_or_copy, replace_when_free, unlink_when_free
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.host import death_is_proven, host_name
from hydromodpy.core.state.layout import LAUNCHER_LEASE_FILENAME, internal_dir

logger = get_logger(__name__)

LEASE_SCHEMA = "hydromodpy.launcher-lease.v1"
"""Schema id of the lease document."""


class LeaseHeldError(WriteConflictError):
    """Another launcher holds the project and its death is not proven."""


@dataclass(frozen=True, slots=True)
class Lease:
    """Who holds the launcher of a project."""

    path: Path
    host: str
    pid: int
    started_at: datetime

    def to_document(self) -> dict[str, object]:
        """Return the JSON document written in the lease file."""
        return {
            "schema": LEASE_SCHEMA,
            "host": self.host,
            "pid": self.pid,
            "started_at": self.started_at.isoformat(),
        }


def lease_path(project_root: Path) -> Path:
    """Return ``<project>/.hmp/launcher.lease``."""
    return internal_dir(Path(project_root)) / LAUNCHER_LEASE_FILENAME


def read_lease(project_root: Path) -> Lease | None:
    """Return the lease of a project, or ``None`` when nobody holds it.

    A lease file that cannot be parsed is a lease being written: it is
    returned with an unknown holder (pid 0) so the caller refuses it. A lease
    of another schema raises
    :class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`, which
    says to delete it.
    """
    return _read_lease_file(lease_path(project_root))


def _read_lease_file(path: Path) -> Lease | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return Lease(path=path, host="", pid=0, started_at=datetime.now(UTC))
    check_document(payload, LEASE_SCHEMA, document=path, remedy=TRANSIENT_REMEDY)
    try:
        return Lease(
            path=path,
            host=str(payload["host"]),
            pid=int(payload["pid"]),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
        )
    except (ValueError, KeyError, TypeError):
        return Lease(path=path, host="", pid=0, started_at=datetime.now(UTC))


def _holder_is_dead(lease: Lease) -> bool:
    """Whether the death of the holder is proven: same host and process gone."""
    return lease.pid > 0 and death_is_proven(lease.host, lease.pid)


def acquire_lease(project_root: Path, *, force: bool = False) -> Lease:
    """Take the lease of *project_root* and return it.

    Raises :class:`LeaseHeldError` naming the holder when a live launcher, or
    a launcher of another host, holds it and *force* is false.
    """
    path = lease_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = Lease(path=path, host=host_name(), pid=os.getpid(), started_at=datetime.now(UTC))
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            held = read_lease(project_root)
            if held is None:
                continue
            if not (force or _holder_is_dead(held)):
                raise _held(path, held) from None
            _take_over(path, held)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(mine.to_document(), handle)
            handle.flush()
            os.fsync(handle.fileno())
        return mine
    raise LeaseHeldError(f"{path} changed hands while it was taken; launch again.")


def _held(path: Path, held: Lease) -> LeaseHeldError:
    return LeaseHeldError(
        f"{path} is held by a launcher on {held.host or 'an unknown host'} "
        f"(pid {held.pid}) since {held.started_at.isoformat(timespec='seconds')}; "
        "wait for it, or pass --force once that launcher is known to be dead."
    )


def _same_holder(a: Lease, b: Lease) -> bool:
    if a.pid == 0 and b.pid == 0:
        # Two reads of a file that does not parse: the same unknown holder.
        return True
    return (a.host, a.pid, a.started_at) == (b.host, b.pid, b.started_at)


def _take_over(path: Path, judged: Lease) -> None:
    """Remove the lease judged dead, and only that one.

    Between the read and the removal another launcher may have taken the
    lease over and written its own. The lease is therefore moved aside
    first, atomically, and read again: the judged lease is removed; a fresh
    one is put back with a link or a copy (neither overwrites) and refused.
    """
    aside = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    try:
        replace_when_free(path, aside)
    except FileNotFoundError:
        # Another launcher moved it first; the next O_EXCL decides.
        return
    taken = _read_lease_file(aside)
    if taken is None or _same_holder(taken, judged):
        _discard(aside)
        return
    try:
        link_or_copy(aside, path)
    except FileExistsError:
        # A third launcher wrote its lease meanwhile: it holds the project now.
        pass
    finally:
        _discard(aside)
    raise _held(path, taken)


def _discard(aside: Path) -> None:
    """Remove a lease moved aside; on Windows a reader that keeps it only gets a warning.

    The lease path is free of it by then, so a file left behind blocks nobody,
    and the error of the take-over is the one that reaches the caller.
    """
    try:
        unlink_when_free(aside)
    except PermissionError as error:
        if os.name != "nt":
            raise
        logger.warning("The lease %s could not be removed (%s).", aside, error)


def release_lease(lease: Lease) -> None:
    """Remove the lease file when it is still the one *lease* wrote."""
    held = read_lease(lease.path.parent.parent)
    if held is not None and held.host == lease.host and held.pid == lease.pid:
        unlink_when_free(lease.path)


@contextmanager
def launcher_lease(project_root: Path, *, force: bool = False) -> Iterator[Lease]:
    """Hold the lease of *project_root* for the block."""
    lease = acquire_lease(project_root, force=force)
    try:
        yield lease
    finally:
        release_lease(lease)


__all__ = [
    "LEASE_SCHEMA",
    "Lease",
    "LeaseHeldError",
    "acquire_lease",
    "launcher_lease",
    "lease_path",
    "read_lease",
    "release_lease",
]
