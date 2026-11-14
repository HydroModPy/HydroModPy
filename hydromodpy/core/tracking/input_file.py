"""Marker and result types for input-file tracking.

A config field that points to a file is annotated with ``InputFile`` and nothing else.
``TrackedFileEntry`` is the record kept for each file, and a new fact kept about each
file is a field of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InputFile:
    """Pydantic field marker for a user-provided input path.

    Attach as an ``Annotated`` metadata entry on any ``Path`` or ``str``
    field that points to an on-disk file or directory. The walker discovers these
    markers at runtime and produces tracked-file entries. ``role`` is also the
    folder of the file under the workspace data folder, so ``workspace:<name>``
    reads ``data/<role>/<name>``.
    """

    role: str
    category: str
    portable: bool = True


def input_file_role(field_info: Any) -> str | None:
    """Return the role of the ``InputFile`` marker of a Pydantic field, or None."""
    for meta in getattr(field_info, "metadata", None) or ():
        if isinstance(meta, InputFile):
            return meta.role
    return None


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
