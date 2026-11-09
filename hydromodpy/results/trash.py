"""Project trash: deleting a run or a session moves its directory, it never flips a flag.

Why
---
The disk is the truth and the index is derived. A trash kept as a status in
the index, or as a marker file inside the run, leaves a deleted run in
``runs/`` where ``ls`` shows it as alive. Here a deleted directory leaves
``runs/`` or ``sessions/`` at once and lands in ``<project>/trash/``, which is
visible and is not under ``.hmp/``: ``rm -rf .hmp`` must never empty the
trash. ``restore`` moves it back. ``gc_trash`` frees the bytes and leaves a
tombstone, so the name of a deleted run is never given to a new run
(:func:`hydromodpy.results.catalog.registration.reserve_version_dirname`
reads both the trash and the tombstones).

Format
------
One trashed directory is named after the relative directory it came from,
with ``/`` replaced by ``__``, then ``@`` and the UTC instant it was trashed::

    trash/runs__baseline_daily.v2@20261014T093000/
    trash/sessions__calibration@20261014T093512/
    trash/sessions__calibration__trials__0004@20261015T080000/

A run or session name never holds ``__`` nor ``@``
(:func:`~hydromodpy.core.state.names.check_name` refuses both), so the name
decodes back to its relative directory.

What may be trashed
-------------------
A directory whose attempt is still beating (``running``) is never moved: its
worker writes into it. One whose attempt stopped beating (``stale``) and one
tagged :data:`PROTECTED_TAG` are moved only when the caller forces it.

``trash/tombstones.txt`` holds one line per directory freed by ``gc_trash``,
``rel_dir,sim_id,date``, with ``date`` the UTC instant of the gc in ISO 8601
and ``sim_id`` empty when the directory carried no identity::

    runs/baseline_daily.v2,9a4f0c1e-...,2026-11-14T09:30:00Z

The file is rewritten whole through a temporary file and ``os.replace``, and
the tombstones are durable before any byte is removed: a crash during a gc
can leave a directory with its tombstone, never a freed name without one.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hydromodpy.core.exceptions import WriteConflictError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import TOMBSTONES_FILENAME, trash_dir_for
from hydromodpy.core.state.result_dirs import parse_rel_dir
from hydromodpy.results.annotations import read_annotations
from hydromodpy.results.manifest import read_seal
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.storage.contract import (
    RUN_PUBLISHED_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
)
from hydromodpy.results.storage.json_io import fsync_directory, readable

logger = get_logger(__name__)

TRASH_STAMP_FORMAT = "%Y%m%dT%H%M%S"
"""UTC instant appended to a trashed directory name, after ``@``."""

TRASH_STAMP_SEPARATOR = "@"
"""Separator between the encoded relative directory and the trash instant."""

TRASH_PATH_SEPARATOR = "__"
"""Stand-in for ``/`` in the name of a trashed directory."""

_TOMBSTONE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

PROTECTED_TAG = "pinned"
"""Tag that keeps a directory out of the trash unless the caller forces it."""


class DirectoryInUseError(WriteConflictError):
    """The directory belongs to an attempt that is running, or may still be."""


class ProtectedDirectoryError(WriteConflictError):
    """The directory carries the protected tag and the caller did not force."""


@dataclass(frozen=True, slots=True)
class TrashedEntry:
    """One directory sitting in ``trash/``."""

    name: str
    """Directory name under ``trash/``, the handle ``restore`` takes."""
    rel_dir: str
    """Relative directory it came from and goes back to (``runs/<name>``)."""
    trashed_at: datetime
    """UTC instant of the move."""
    path: Path
    """Absolute path of the trashed directory."""


@dataclass(frozen=True, slots=True)
class Tombstone:
    """One line of ``trash/tombstones.txt``: a name freed on disk, never reused."""

    rel_dir: str
    sim_id: str | None
    """``sim_id`` of a run, ``session_id`` of a session, None when unknown."""
    date: datetime
    """UTC instant the gc removed the directory."""

    def to_line(self) -> str:
        """Return the line written to ``tombstones.txt``, without its newline."""
        return ",".join((self.rel_dir, self.sim_id or "", _format_utc(self.date)))

    @classmethod
    def from_line(cls, line: str) -> Tombstone:
        """Parse one line; ``ValueError`` names what is wrong."""
        parts = line.split(",")
        if len(parts) != 3:
            raise ValueError(f"expected 'rel_dir,sim_id,date', got {line!r}")
        rel_dir, sim_id, stamp = (part.strip() for part in parts)
        parse_rel_dir(rel_dir)
        date = datetime.strptime(stamp, _TOMBSTONE_DATE_FORMAT).replace(tzinfo=UTC)
        return cls(rel_dir=rel_dir, sim_id=sim_id or None, date=date)


def trashed_dirname(rel_dir: str, at: datetime) -> str:
    """Return the name a directory takes under ``trash/`` when trashed at ``at``."""
    parsed = parse_rel_dir(rel_dir).as_posix()
    encoded = parsed.replace("/", TRASH_PATH_SEPARATOR)
    return f"{encoded}{TRASH_STAMP_SEPARATOR}{as_utc(at).strftime(TRASH_STAMP_FORMAT)}"


def parse_trashed_dirname(name: str) -> tuple[str, datetime]:
    """Return ``(rel_dir, trashed_at)`` of a trashed directory name.

    Raises ``ValueError`` for a name this module did not write.
    """
    encoded, sep, stamp = name.rpartition(TRASH_STAMP_SEPARATOR)
    if not sep or not encoded:
        raise ValueError(f"{name!r} is not a trashed directory name (no '@<stamp>')")
    trashed_at = datetime.strptime(stamp, TRASH_STAMP_FORMAT).replace(tzinfo=UTC)
    rel_dir = encoded.replace(TRASH_PATH_SEPARATOR, "/")
    return parse_rel_dir(rel_dir).as_posix(), trashed_at


def is_protected(directory: Path) -> bool:
    """Return whether ``directory`` carries :data:`PROTECTED_TAG`.

    Annotations this code cannot read may carry it: the directory stays protected.
    """
    annotations = readable(read_annotations, directory)
    return annotations is None or PROTECTED_TAG in annotations.tags


def trash_run(project_root: Path, rel_dir: str, *, now: datetime, force: bool = False) -> Path:
    """Move ``<project>/<rel_dir>`` into ``trash/`` and return its new path.

    ``rel_dir`` is a run (``runs/<name>``), a session (``sessions/<name>``)
    or a kept trial. A directory that was published (it holds
    ``published.jsonl``) is trashed all the same, with a warning: copies of
    it live elsewhere and keep pointing at a source that is now in the trash.

    Raises :class:`DirectoryInUseError` for a running attempt, and for a
    stale one unless ``force``; :class:`ProtectedDirectoryError` for a
    protected directory unless ``force``.
    """
    root = Path(project_root)
    rel = parse_rel_dir(rel_dir).as_posix()
    source = root / rel
    if not source.is_dir():
        raise FileNotFoundError(f"{rel} is not a directory of the project {root}")
    _check_movable(source, rel, force=force)
    if (source / RUN_PUBLISHED_FILENAME).is_file():
        logger.warning(
            "%s was published (see %s): the published copies now point at a trashed source",
            rel,
            RUN_PUBLISHED_FILENAME,
        )
    trash_dir = trash_dir_for(root)
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / trashed_dirname(rel, now)
    if target.exists():
        raise FileExistsError(f"{target} already exists; trash {rel} again in a second")
    os.rename(source, target)
    return target


def check_not_running(directory: Path, rel_dir: str, *, force: bool = False) -> None:
    """Refuse a directory a live attempt writes into; a stale one passes with ``force``.

    The state is :func:`hydromodpy.results.outcome.effective_status`: a
    directory without ``outcome.json`` has no attempt and always passes.
    """
    state = effective_status(directory)
    if state == "running":
        raise DirectoryInUseError(
            f"{rel_dir} is running: its attempt is still beating. Stop it first."
        )
    if state == "stale" and not force:
        raise DirectoryInUseError(
            f"{rel_dir} is stale: its attempt stopped beating without an outcome. "
            "`hmp catalog gc -y` marks it aborted; --force acts on it as it is."
        )


def _check_movable(directory: Path, rel_dir: str, *, force: bool) -> None:
    check_not_running(directory, rel_dir, force=force)
    if not force and is_protected(directory):
        raise ProtectedDirectoryError(
            f"{rel_dir} is tagged '{PROTECTED_TAG}'; pass --force to trash it."
        )


def restore(project_root: Path, trashed_name: str) -> Path:
    """Move a trashed directory back where it came from and return that path."""
    root = Path(project_root)
    rel, _ = parse_trashed_dirname(trashed_name)
    source = trash_dir_for(root) / trashed_name
    if not source.is_dir():
        raise FileNotFoundError(f"{trashed_name} is not in the trash of {root}")
    target = root / rel
    if target.exists():
        raise FileExistsError(f"{rel} exists again; move it away before restoring {trashed_name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, target)
    return target


def list_trash(project_root: Path) -> list[TrashedEntry]:
    """Return the trashed directories, oldest first.

    An entry of ``trash/`` this module did not name (a file, a folder made by
    hand) is skipped: it carries no relative directory to restore to.
    """
    trash_dir = trash_dir_for(Path(project_root))
    if not trash_dir.is_dir():
        return []
    entries: list[TrashedEntry] = []
    for path in trash_dir.iterdir():
        if not path.is_dir():
            continue
        try:
            rel, trashed_at = parse_trashed_dirname(path.name)
        except ValueError:
            logger.debug("skipping %s: not a trashed directory name", path)
            continue
        entries.append(TrashedEntry(name=path.name, rel_dir=rel, trashed_at=trashed_at, path=path))
    entries.sort(key=lambda entry: (entry.trashed_at, entry.name))
    return entries


def read_tombstones(project_root: Path) -> list[Tombstone]:
    """Return the tombstones of the project, in file order.

    A malformed line raises ``ValueError`` with its line number: a tombstone
    that cannot be read would let a deleted name be given out again.
    """
    path = trash_dir_for(Path(project_root)) / TOMBSTONES_FILENAME
    if not path.is_file():
        return []
    tombstones: list[Tombstone] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            tombstones.append(Tombstone.from_line(line))
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    return tombstones


def purge_trashed(
    project_root: Path, entries: list[TrashedEntry], *, now: datetime
) -> list[Tombstone]:
    """Remove trashed directories for good and return their tombstones.

    The tombstones are written and flushed to disk before the first removal,
    so a crash can leave a directory with its tombstone, never a freed name
    without one.
    """
    root = Path(project_root)
    if not entries:
        return []
    stamp = as_utc(now).replace(microsecond=0)
    new = [
        Tombstone(rel_dir=entry.rel_dir, sim_id=identity_of(entry.path), date=stamp)
        for entry in entries
    ]
    _write_tombstones(root, [*read_tombstones(root), *new])
    for entry in entries:
        if (entry.path / RUN_PUBLISHED_FILENAME).is_file():
            logger.warning(
                "%s was published (see %s): its published copies lose their source for good",
                entry.rel_dir,
                RUN_PUBLISHED_FILENAME,
            )
        shutil.rmtree(entry.path)
    return new


def expired_entries(
    project_root: Path, *, older_than: timedelta, now: datetime
) -> list[TrashedEntry]:
    """Return the entries trashed at least ``older_than`` before ``now``."""
    cutoff = as_utc(now) - older_than
    return [entry for entry in list_trash(Path(project_root)) if entry.trashed_at <= cutoff]


def gc_trash(project_root: Path, *, older_than: timedelta, now: datetime) -> list[Tombstone]:
    """Remove the directories trashed at least ``older_than`` before ``now``.

    Each removed directory leaves a tombstone (:func:`purge_trashed`).
    Returns the new tombstones.
    """
    root = Path(project_root)
    return purge_trashed(root, expired_entries(root, older_than=older_than, now=now), now=now)


def remove_for_good(
    project_root: Path, rel_dir: str, *, now: datetime, force: bool = False
) -> Path:
    """Move a run to the trash, then purge it there, and return where it went.

    The purge leaves a tombstone, so the name of the run stays taken.
    """
    trashed = trash_run(project_root, rel_dir, now=now, force=force)
    entry = next(entry for entry in list_trash(project_root) if entry.path == trashed)
    purge_trashed(project_root, [entry], now=now)
    return trashed


def identity_of(directory: Path) -> str | None:
    """Return the ``sim_id`` or ``session_id`` a directory declares, if any."""
    seal = readable(read_seal, directory)
    if seal is not None:
        return seal.run.sim_id
    outcome = readable(read_outcome, directory)
    if outcome is not None and outcome.sim_id:
        return str(outcome.sim_id)
    if (directory / SESSION_DESCRIPTOR_FILENAME).is_file():
        descriptor = readable(read_session, directory)
        if descriptor is not None and descriptor.session_id:
            return str(descriptor.session_id)
    return None


def _write_tombstones(project_root: Path, tombstones: list[Tombstone]) -> None:
    """Rewrite ``tombstones.txt`` atomically and durably."""
    trash_dir = trash_dir_for(project_root)
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / TOMBSTONES_FILENAME
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    text = "".join(f"{tombstone.to_line()}\n" for tombstone in tombstones)
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    fsync_directory(trash_dir)


def as_utc(value: datetime) -> datetime:
    """Return ``value`` in UTC; a naive value is taken as UTC already."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return as_utc(value).strftime(_TOMBSTONE_DATE_FORMAT)


__all__ = [
    "PROTECTED_TAG",
    "TRASH_PATH_SEPARATOR",
    "TRASH_STAMP_FORMAT",
    "TRASH_STAMP_SEPARATOR",
    "DirectoryInUseError",
    "ProtectedDirectoryError",
    "Tombstone",
    "TrashedEntry",
    "check_not_running",
    "expired_entries",
    "gc_trash",
    "identity_of",
    "is_protected",
    "list_trash",
    "parse_trashed_dirname",
    "purge_trashed",
    "read_tombstones",
    "remove_for_good",
    "restore",
    "trash_run",
    "trashed_dirname",
]
