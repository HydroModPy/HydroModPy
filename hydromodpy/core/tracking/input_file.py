"""Marker and result types for input-file tracking.

A config field that points to a file is annotated with ``InputFile`` and nothing else.
``TrackedFileEntry`` is the record kept for each file, and a new fact kept about each
file is a field of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InputFile:
    """Pydantic field marker for a user-provided input path.

    Attach as an ``Annotated`` metadata entry on any ``Path`` or ``str``
    field that points to an on-disk file or directory. The walker discovers these
    markers at runtime and produces tracked-file entries.
    """

    role: str
    category: str
    portable: bool = True


@dataclass(frozen=True)
class TrackedFileEntry:
    """Resolved tracked-file record returned by the walker."""

    role: str
    category: str
    original_path: str
    canonical_path: Path
    portable: bool

    def exists(self) -> bool:
        return self.canonical_path.exists()
