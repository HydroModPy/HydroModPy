"""Trash state of a run: the marker that outlives the index.

Why
---
``.hmp/index.duckdb`` is an index rebuilt from the run directories, so a state
that lives only in SQL is lost the day it is deleted. Trashing a run is a
status flip that moves no bytes: without a sidecar, ``hmp catalog reindex``
silently brings every trashed run back as the completed run it was, and the
user finds a directory they had discarded back in ``hmp catalog list``.

What
----
``runs/<name>/trash.json`` holds it, next to ``annotations.json``. Present
means trashed, absent means live, so the disk answers the question on its own.
Like the annotations sidecar it is written after the seal, so the manifest
neither lists nor sizes it, and the index stays authoritative while it exists:
:meth:`Catalog.trash` writes the DuckDB row first, then this file.

Format
------
.. code-block:: json

    {
      "trash_version": 1,
      "sim_id": "3060a003-1226-4b32-a0dd-05806d678a0a",
      "original_name": "cheze_baseline",
      "original_status": "completed",
      "trashed_at": "2026-07-26T09:12:44+00:00"
    }
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from hydromodpy.results.storage.contract import RUN_TRASH_FILENAME

TRASH_VERSION = 1
"""Schema version of the trash sidecar."""


@dataclass(frozen=True, slots=True)
class TrashMarker:
    """Trash state of one run: the name and status it must come back as."""

    original_name: str
    original_status: str
    trashed_at: str


def trash_marker_path(run_dir: Path | str) -> Path:
    """Return the trash marker path of a run directory."""
    return Path(run_dir) / RUN_TRASH_FILENAME


def read_trash_marker(run_dir: Path | str) -> TrashMarker | None:
    """Read ``trash.json``, ``None`` when the run is not trashed.

    A malformed file raises: the rebuild reports the run instead of quietly
    resurrecting something the user discarded.
    """
    target = trash_marker_path(run_dir)
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} does not hold a trash marker object")
    original_name = payload.get("original_name")
    if not original_name:
        raise ValueError(f"{target} holds no original_name to restore the run under")
    return TrashMarker(
        original_name=str(original_name),
        original_status=str(payload.get("original_status") or "completed"),
        trashed_at=str(payload.get("trashed_at") or ""),
    )


def write_trash_marker(
    run_dir: Path | str,
    marker: TrashMarker,
    *,
    sim_id: str | UUID,
) -> Path | None:
    """Write the marker atomically. ``None`` when the run has no directory yet."""
    target = trash_marker_path(run_dir)
    if not target.parent.is_dir():
        return None
    payload = {
        "trash_version": TRASH_VERSION,
        "sim_id": str(sim_id),
        "original_name": marker.original_name,
        "original_status": marker.original_status,
        "trashed_at": marker.trashed_at,
    }
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def clear_trash_marker(run_dir: Path | str) -> None:
    """Remove the marker, so the directory reads as a live run again."""
    trash_marker_path(run_dir).unlink(missing_ok=True)


__all__ = [
    "TRASH_VERSION",
    "TrashMarker",
    "clear_trash_marker",
    "read_trash_marker",
    "trash_marker_path",
    "write_trash_marker",
]
