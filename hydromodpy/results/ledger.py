"""The ledger of a ``figures/`` or ``exports/`` directory: ``index.json``.

Why
---
A figure or an export is derived: it can be rendered again from the sealed
run. What cannot be recovered is how it was made: by which producer, with
which options, under which version, and what the run was called that day.
The ledger keeps one entry per file so ``hmp export --regen`` replays it, and so a reader knows what a file is
without opening it. :func:`record_derived_file` adds the entry of a file a
figure or an export just wrote, under ``index.json.lock`` beside it: a
:class:`~hydromodpy.core.io.lock_file.LockFile` that names its process, its
host and its date, taken back when that process died on this host or after
60 s. The same lock holds on every system.

Format
------
``{"schema": "hydromodpy.ledger.v1", "entries": [{"file": "heads.png",
"producer": "display:figure", "options": {...}, "hydromodpy_version":
"2.0.0a5", "at": "<UTC instant>", "sha256": "...", "identity": {...}}]}``.
``file`` is relative to the directory of the ledger. Appending an entry for a
file the ledger already names replaces it: one file, one entry.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import dump_stored, read_stored
from hydromodpy.core.exceptions import WriteConflictError
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.io.lock_file import LockFile
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.identity import Identity
from hydromodpy.results.storage.contract import LEDGER_FILENAME
from hydromodpy.results.storage.json_io import read_sealed_json, write_json_atomic

LEDGER_SCHEMA: Final[str] = "hydromodpy.ledger.v1"
"""Schema id of the document."""

LEDGER_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.ledger.v1", current=LEDGER_SCHEMA
)
"""Versions of the document this code reads."""

LEDGER_LOCK_SUFFIX: Final[str] = ".lock"
"""Suffix of the lock file, beside the ledger."""

LEDGER_LOCK_STALE_S: Final[float] = 60.0
"""Age past which the lock of a ledger is stale. Reading and writing a ledger lasts milliseconds."""

LEDGER_LOCK_WAIT_S: Final[float] = 90.0
"""How long a writer waits. Longer than the staleness, so a lock left behind is always taken back."""


class LedgerEntry(HydroModelBase):
    """How one file of the directory was made."""

    file: str = Field(description="Path of the file, relative to the ledger directory")
    producer: str = Field(description="Name of the producer that wrote the file")
    options: dict[str, Any] = Field(default_factory=dict, description="Options it was given")
    hydromodpy_version: str = Field(description="Version that wrote the file")
    at: datetime = Field(description="Instant the file was written, UTC")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of the file")
    identity: Identity | None = Field(
        default=None,
        description=(
            "Identity block posed in the file; none for a file drawn from many runs "
            "(summary/ tables and cohort figures)"
        ),
    )

    @model_validator(mode="after")
    def _relative(self) -> LedgerEntry:
        if Path(self.file).is_absolute() or ".." in Path(self.file).parts:
            raise ValueError(f"a ledger names a file inside its directory, not {self.file!r}")
        return self


class Ledger(HydroModelBase):
    """The entries of one directory."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=LEDGER_SCHEMA, alias="schema", description="Schema id")
    entries: list[LedgerEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_entry_per_file(self) -> Ledger:
        if not LEDGER_VERSIONS.holds(self.schema_):
            raise ValueError(f"schema is {self.schema_!r}, this module reads {LEDGER_SCHEMA!r}")
        files = [entry.file for entry in self.entries]
        if len(files) != len(set(files)):
            raise ValueError(f"a ledger names each file once: {sorted(files)}")
        return self

    @classmethod
    def read(cls, directory: str | Path) -> Ledger:
        """Return the ledger of a directory, empty when it has none."""
        try:
            payload = read_sealed_json(ledger_path(directory), LEDGER_VERSIONS)
        except FileNotFoundError:
            return cls()
        return read_stored(cls, payload)

    def entry_for(self, file: str) -> LedgerEntry | None:
        """Return the entry of *file*, or ``None``."""
        return next((entry for entry in self.entries if entry.file == file), None)

    def append(self, entry: LedgerEntry) -> None:
        """Add *entry*, replacing the entry of the same file if any.

        The list is changed in place: an assignment would validate the model
        again and lose the unknown keys its reading kept.
        """
        self.entries[:] = [kept for kept in self.entries if kept.file != entry.file] + [entry]

    def write(self, directory: str | Path) -> Path:
        """Write the ledger atomically and return its path."""
        return write_json_atomic(ledger_path(directory), dump_stored(self))


def ledger_path(directory: str | Path) -> Path:
    """Return ``<directory>/index.json``."""
    return Path(directory) / LEDGER_FILENAME


def record_derived_file(
    directory: str | Path,
    path: str | Path,
    *,
    producer: str,
    options: Mapping[str, Any],
    identity: Identity,
) -> LedgerEntry:
    """Add the entry of *path* to the ledger of *directory* and return it.

    *path* lies under *directory*; the entry names it relative to it. An entry
    for the same file is replaced: one file, one entry.
    """
    root = Path(directory)
    target = Path(path)
    entry = LedgerEntry(
        file=target.resolve().relative_to(root.resolve()).as_posix(),
        producer=producer,
        options=dict(options),
        hydromodpy_version=HYDROMODPY_VERSION,
        at=datetime.now(UTC),
        sha256=sha256_of(target),
        identity=identity,
    )
    with _locked(root) as lock:
        ledger = Ledger.read(root)
        ledger.append(entry)
        if not lock.still_held():
            raise WriteConflictError(
                f"The lock of the ledger {ledger_path(root)} was taken back while "
                f"{target.name} was recorded. Record it again.",
                ledger=str(ledger_path(root)),
            )
        ledger.write(root)
    return entry


@contextmanager
def _locked(directory: Path) -> Iterator[LockFile]:
    """Hold the lock of the ledger of *directory* while it is read, changed and written.

    Two writers would otherwise read the same ledger and the later write would
    drop the entry of the earlier one.
    """
    path = ledger_path(directory)
    lock = LockFile(
        path.with_name(f"{path.name}{LEDGER_LOCK_SUFFIX}"),
        stale_after_s=LEDGER_LOCK_STALE_S,
        wait_s=LEDGER_LOCK_WAIT_S,
    )
    if not lock.acquire():
        raise WriteConflictError(
            f"The ledger {path} is being written by another process past "
            f"{LEDGER_LOCK_WAIT_S:.0f} s. Remove {lock.path.name} once that process is gone.",
            ledger=str(path),
        )
    try:
        yield lock
    finally:
        lock.release()


__all__ = ["LEDGER_SCHEMA", "Ledger", "LedgerEntry", "ledger_path", "record_derived_file"]
