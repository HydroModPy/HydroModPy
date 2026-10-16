"""The ledger of a ``figures/`` or ``exports/`` directory: ``index.json``.

Why
---
A figure or an export is derived: it can be rendered again from the sealed
run. What cannot be recovered is how it was made: by which producer, with
which options, under which version, and what the run was called that day.
The ledger keeps one entry per file so ``hmp viz regen`` and
``hmp export --regen`` replay it, and so a reader knows what a file is
without opening it.

Format
------
``{"schema": "hydromodpy.ledger.v1", "entries": [{"file": "heads.png",
"producer": "display.figures.heads", "options": {...}, "hydromodpy_version":
"2.0.0a5", "at": "<UTC instant>", "sha256": "...", "identity": {...}}]}``.
``file`` is relative to the directory of the ledger. Appending an entry for a
file the ledger already names replaces it: one file, one entry.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.results.identity import Identity
from hydromodpy.results.storage.contract import LEDGER_FILENAME
from hydromodpy.results.storage.json_io import read_json, write_json_atomic

LEDGER_SCHEMA: Final[str] = "hydromodpy.ledger.v1"
"""Schema id of the document."""


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
        if self.schema_ != LEDGER_SCHEMA:
            raise ValueError(f"schema is {self.schema_!r}, this module reads {LEDGER_SCHEMA!r}")
        files = [entry.file for entry in self.entries]
        if len(files) != len(set(files)):
            raise ValueError(f"a ledger names each file once: {sorted(files)}")
        return self

    @classmethod
    def read(cls, directory: str | Path) -> Ledger:
        """Return the ledger of a directory, empty when it has none."""
        try:
            payload = read_json(ledger_path(directory))
        except FileNotFoundError:
            return cls()
        return cls.model_validate(payload)

    def entry_for(self, file: str) -> LedgerEntry | None:
        """Return the entry of *file*, or ``None``."""
        return next((entry for entry in self.entries if entry.file == file), None)

    def append(self, entry: LedgerEntry) -> None:
        """Add *entry*, replacing the entry of the same file if any."""
        self.entries = [kept for kept in self.entries if kept.file != entry.file] + [entry]

    def write(self, directory: str | Path) -> Path:
        """Write the ledger atomically and return its path."""
        return write_json_atomic(
            ledger_path(directory), self.model_dump(mode="json", by_alias=True)
        )


def ledger_path(directory: str | Path) -> Path:
    """Return ``<directory>/index.json``."""
    return Path(directory) / LEDGER_FILENAME


def sha256_of(path: str | Path) -> str:
    """Return the hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["LEDGER_SCHEMA", "Ledger", "LedgerEntry", "ledger_path", "sha256_of"]
