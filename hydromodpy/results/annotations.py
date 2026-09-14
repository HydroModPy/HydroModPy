"""Run annotations: the tags and notes that outlive the index.

Why
---
``.hmp/index.duckdb`` is rebuildable from the run directories, so anything
that lives only in SQL is lost the day it is deleted. Tags and notes are
written by a human after the run is sealed, and no other file can give them
back: without a sidecar, ``hmp catalog reindex`` silently drops a ``pinned``
flag or a "keep, best fit" note.

What
----
``runs/<name>/annotations.json`` holds them, next to ``manifest.json``. It is
the only file of a run directory that changes after the seal, so the manifest
neither lists nor sizes it. The index stays authoritative while it exists:
every mutation writes the DuckDB row first, then rewrites this file from the
rows, so the file is a projection and never a second source of truth.

Format
------
.. code-block:: json

    {
      "annotations_version": 1,
      "sim_id": "3060a003-1226-4b32-a0dd-05806d678a0a",
      "tags": ["pinned", "calibration:0b719164..."],
      "notes": [
        {"note": "best fit after widening Sy bounds",
         "added_at": "2026-07-25T22:24:31+00:00",
         "added_by": null}
      ]
    }
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from hydromodpy.results.storage.contract import RUN_ANNOTATIONS_FILENAME

ANNOTATIONS_VERSION = 1
"""Schema version of the annotations sidecar."""


@dataclass(frozen=True, slots=True)
class RunNote:
    """One timestamped note attached to a run."""

    note: str
    added_at: str
    added_by: str | None = None


@dataclass(frozen=True, slots=True)
class RunAnnotations:
    """Tags and notes of one run."""

    tags: tuple[str, ...] = ()
    notes: tuple[RunNote, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when the run carries neither a tag nor a note."""
        return not self.tags and not self.notes


def annotations_path(run_dir: Path | str) -> Path:
    """Return the annotations sidecar path of a run directory."""
    return Path(run_dir) / RUN_ANNOTATIONS_FILENAME


def read_annotations(run_dir: Path | str) -> RunAnnotations:
    """Read ``annotations.json``, empty when the run carries none.

    A malformed file raises: the rebuild reports the run instead of dropping
    annotations it cannot parse.
    """
    target = annotations_path(run_dir)
    if not target.is_file():
        return RunAnnotations()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} does not hold an annotations object")
    return RunAnnotations(
        tags=tuple(str(tag) for tag in payload.get("tags", ())),
        notes=tuple(_note_from_payload(item, target) for item in payload.get("notes", ())),
    )


def write_annotations(
    run_dir: Path | str,
    annotations: RunAnnotations,
    *,
    sim_id: str | UUID,
) -> Path | None:
    """Write the sidecar atomically, or remove it when nothing is left.

    Returns the written path, or ``None`` when the last tag and note were
    removed and the file was deleted with them.
    """
    target = annotations_path(run_dir)
    if annotations.is_empty:
        target.unlink(missing_ok=True)
        return None
    payload = {
        "annotations_version": ANNOTATIONS_VERSION,
        "sim_id": str(sim_id),
        "tags": list(annotations.tags),
        "notes": [
            {"note": note.note, "added_at": note.added_at, "added_by": note.added_by}
            for note in annotations.notes
        ],
    }
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def _note_from_payload(item: Any, target: Path) -> RunNote:
    """Build one :class:`RunNote` from its JSON object."""
    if not isinstance(item, dict) or "note" not in item:
        raise ValueError(f"{target} holds a note without its text")
    added_by = item.get("added_by")
    return RunNote(
        note=str(item["note"]),
        added_at=str(item.get("added_at", "")),
        added_by=None if added_by is None else str(added_by),
    )


__all__ = [
    "ANNOTATIONS_VERSION",
    "RunAnnotations",
    "RunNote",
    "annotations_path",
    "read_annotations",
    "write_annotations",
]
