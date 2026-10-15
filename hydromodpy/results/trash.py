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

    trash/runs__nancon_daily.v2@20261014T093000/
    trash/sessions__calibration@20261014T093512/
    trash/sessions__calibration__trials__0004@20261015T080000/

A run or session name never holds ``__`` (``run_dirname`` collapses repeated
underscores) nor ``@``, so the name decodes back to its relative directory.

``trash/tombstones.txt`` holds one line per directory freed by ``gc_trash``,
``rel_dir,sim_id,date``, with ``date`` the UTC instant of the gc in ISO 8601
and ``sim_id`` empty when the directory carried no identity::

    runs/nancon_daily.v2,9a4f0c1e-...,2026-11-14T09:30:00Z

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

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    TOMBSTONES_FILENAME,
    parse_rel_dir,
    trash_dir_for,
)
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.storage.contract import (
    RUN_PUBLISHED_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
)

logger = get_logger(__name__)

TRASH_STAMP_FORMAT = "%Y%m%dT%H%M%S"
"""UTC instant appended to a trashed directory name, after ``@``."""

TRASH_STAMP_SEPARATOR = "@"
"""Separator between the encoded relative directory and the trash instant."""

TRASH_PATH_SEPARATOR = "__"
"""Stand-in for ``/`` in the name of a trashed directory."""

_TOMBSTONE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


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
    return f"{encoded}{TRASH_STAMP_SEPARATOR}{_as_utc(at).strftime(TRASH_STAMP_FORMAT)}"


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


def trash_run(project_root: Path, rel_dir: str, *, now: datetime) -> Path:
    """Move ``<project>/<rel_dir>`` into ``trash/`` and return its new path.

    ``rel_dir`` is a run (``runs/<name>``), a session (``sessions/<name>``)
    or a kept trial. A directory that was published (it holds
    ``published.jsonl``) is trashed all the same, with a warning: copies of
    it live elsewhere and keep pointing at a source that is now in the trash.
    """
    root = Path(project_root)
    rel = parse_rel_dir(rel_dir).as_posix()
    source = root / rel
    if not source.is_dir():
        raise FileNotFoundError(f"{rel} is not a directory of the project {root}")
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


def gc_trash(project_root: Path, *, older_than: timedelta, now: datetime) -> list[Tombstone]:
    """Remove the directories trashed at least ``older_than`` before ``now``.

    Each removed directory leaves a tombstone. The tombstones are written and
    flushed to disk before the first removal. Returns the new tombstones.
    """
    root = Path(project_root)
    cutoff = _as_utc(now) - older_than
    expired = [entry for entry in list_trash(root) if entry.trashed_at <= cutoff]
    if not expired:
        return []
    stamp = _as_utc(now).replace(microsecond=0)
    new = [
        Tombstone(rel_dir=entry.rel_dir, sim_id=_identity_of(entry.path), date=stamp)
        for entry in expired
    ]
    _write_tombstones(root, [*read_tombstones(root), *new])
    for entry in expired:
        shutil.rmtree(entry.path)
    return new


def _identity_of(directory: Path) -> str | None:
    """Return the ``sim_id`` or ``session_id`` a directory declares, if any."""
    # Imported here: the v1 manifest writer still imports the catalog package,
    # whose registration module imports this one. The import moves to the
    # module level when L1 retires that writer.
    from hydromodpy.results.manifest import is_sealed, read_manifest

    outcome = read_outcome(directory)
    if outcome is not None and outcome.sim_id:
        return str(outcome.sim_id)
    if is_sealed(directory):
        sim_id = read_manifest(directory).get("run", {}).get("sim_id")
        if sim_id:
            return str(sim_id)
    if (directory / SESSION_DESCRIPTOR_FILENAME).is_file():
        session_id = read_session(directory).session_id
        if session_id:
            return str(session_id)
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
    _fsync_directory(trash_dir)


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry to disk where the platform allows it."""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _as_utc(value: datetime) -> datetime:
    """Return ``value`` in UTC; a naive value is taken as UTC already."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return _as_utc(value).strftime(_TOMBSTONE_DATE_FORMAT)


__all__ = [
    "TRASH_PATH_SEPARATOR",
    "TRASH_STAMP_FORMAT",
    "TRASH_STAMP_SEPARATOR",
    "Tombstone",
    "TrashedEntry",
    "gc_trash",
    "list_trash",
    "parse_trashed_dirname",
    "read_tombstones",
    "restore",
    "trash_run",
    "trashed_dirname",
]
