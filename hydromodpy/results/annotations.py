"""Run annotations: the tags and notes a human adds after the seal.

Why
---
``.hmp/index.duckdb`` is rebuilt from the run directories, so anything that
lived only in SQL would be lost the day it is deleted. Tags and notes are
written by a human after the run is sealed, and no other file can give them
back. They live in the run directory, and the index reads them from there
when it indexes the run.

What
----
``runs/<name>/annotations.json`` holds them, next to ``manifest.json``. It is
the only file of a run directory that changes after the seal, so the manifest
neither lists nor sizes it. :func:`add_tag`, :func:`remove_tag` and
:func:`add_note` read the file, change it and write it back atomically;
``Run.tag``, ``Run.note``, ``hmp catalog tag`` and ``hmp catalog note`` go
through them.

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

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import dump_stored, read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.results.manifest import is_sealed, read_seal
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.contract import RUN_ANNOTATIONS_FILENAME
from hydromodpy.results.storage.json_io import read_sealed_json, write_json_atomic

ANNOTATIONS_VERSION: Final[int] = 1
"""Schema version of the annotations file."""

ANNOTATIONS_VERSIONS: Final[VersionWindow] = VersionWindow(oldest=1, current=ANNOTATIONS_VERSION)
"""Versions of the annotations file this code reads."""


class Note(HydroModelBase):
    """One timestamped note attached to a run."""

    text: str = Field(alias="note", description="The note, as its author wrote it")
    author: str | None = Field(default=None, alias="added_by", description="Who wrote it")
    at: datetime = Field(alias="added_at", description="When it was written, UTC")

    model_config = ConfigDict(populate_by_name=True)


class Annotations(HydroModelBase):
    """Tags and notes of one run."""

    annotations_version: int = ANNOTATIONS_VERSION
    sim_id: str | None = Field(default=None, description="Id of the run the file belongs to")
    tags: tuple[str, ...] = ()
    notes: tuple[Note, ...] = ()


def annotations_path(run_dir: Path | str) -> Path:
    """Return ``<run>/annotations.json``."""
    return Path(run_dir) / RUN_ANNOTATIONS_FILENAME


def read_annotations(run_dir: Path | str) -> Annotations:
    """Read ``annotations.json``, empty when the run carries none.

    A malformed file raises. The indexer keeps the run and warns, and the file
    stays as it is.
    """
    target = annotations_path(run_dir)
    if not target.is_file():
        return Annotations()
    return read_stored(
        Annotations, read_sealed_json(target, ANNOTATIONS_VERSIONS, key="annotations_version")
    )


def write_annotations(run_dir: Path | str, annotations: Annotations) -> Path:
    """Write ``annotations.json`` atomically and return its path.

    The file names the run it belongs to: a missing ``sim_id`` is read from
    the outcome or the seal of the directory.
    """
    directory = Path(run_dir)
    if annotations.sim_id is None:
        annotations = annotations.model_copy(update={"sim_id": _sim_id_of(directory)})
    return write_json_atomic(annotations_path(directory), dump_stored(annotations))


def add_tag(run_dir: Path | str, tag: str) -> Annotations:
    """Add *tag* to the run, once; return the annotations written."""
    current = read_annotations(run_dir)
    if tag in current.tags:
        return current
    updated = current.model_copy(update={"tags": (*current.tags, tag)})
    write_annotations(run_dir, updated)
    return updated


def remove_tag(run_dir: Path | str, tag: str) -> Annotations:
    """Remove *tag* from the run when it carries it; return the annotations."""
    current = read_annotations(run_dir)
    if tag not in current.tags:
        return current
    updated = current.model_copy(update={"tags": tuple(t for t in current.tags if t != tag)})
    write_annotations(run_dir, updated)
    return updated


def add_note(
    run_dir: Path | str,
    text: str,
    *,
    author: str | None = None,
    now: datetime | None = None,
) -> Annotations:
    """Append a note to the run, stamped *now* (UTC by default); return the annotations."""
    current = read_annotations(run_dir)
    note = Note(text=text, author=author, at=now or datetime.now(UTC))
    updated = current.model_copy(update={"notes": (*current.notes, note)})
    write_annotations(run_dir, updated)
    return updated


def _sim_id_of(run_dir: Path) -> str | None:
    """Return the ``sim_id`` the seal of *run_dir* declares, else its outcome."""
    if is_sealed(run_dir):
        return read_seal(run_dir).run.sim_id
    outcome = read_outcome(run_dir)
    return None if outcome is None or not outcome.sim_id else str(outcome.sim_id)


__all__ = [
    "ANNOTATIONS_VERSION",
    "ANNOTATIONS_VERSIONS",
    "Annotations",
    "Note",
    "add_note",
    "add_tag",
    "annotations_path",
    "read_annotations",
    "remove_tag",
    "write_annotations",
]
