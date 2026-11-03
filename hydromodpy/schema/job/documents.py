"""How a job writes one of its documents: whole, or not at all.

Every document of a job directory is written through here, so a reader never
catches one half-written and the seal never hashes bytes that were still
being appended to. The rendering keeps the order the writing code chose,
because these files are read by people before they are read by programs; what
is canonicalised is what gets **hashed**, not what gets written.

A stored document of a job carries its version in ``schema``, such as
``hmp-outcome/v1``. Its reader follows the rule of every stored document
(:mod:`hydromodpy.core.io.document_version`) through :func:`read_versioned`, and a key
it does not know reads. A request is an input, not a stored result, so
:func:`read_document` reads it with no version.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.core.io.document_version import VersionWindow, check_version
from hydromodpy.schema.job.layout import JOB_PROVENANCE_FILENAME


def render_document(payload: Any) -> str:
    """Render *payload* as the exact text a job document carries."""
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def write_document(path: str | Path, payload: Any) -> Path:
    """Write *payload* to *path* through a temporary file and one rename."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # uuid, not the pid: two writers of the same document inside one process
    # would otherwise pick the same temporary name and overwrite each other's
    # bytes before either rename. This is the spelling the run manifest uses.
    tmp = target.with_name(f"{target.name}.tmp-{uuid4().hex}")
    tmp.write_text(render_document(payload), encoding="utf-8")
    rename_over_open_file(tmp, target)
    return target


def read_document(path: str | Path) -> Any:
    """Read a job document back."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_versioned(path: str | Path, window: VersionWindow) -> Any:
    """Read a stored job document; refuse it unless its ``schema`` lies inside *window*."""
    return check_job_document(read_document(path), window, path=path)


def check_job_document(payload: Any, window: VersionWindow, *, path: str | Path) -> Any:
    """Return a job document read from *path*; refuse it unless its ``schema`` is in *window*."""
    found = payload.get("schema") if isinstance(payload, Mapping) else None
    if not window.holds(found):
        target = Path(path)
        check_version(found, window, document=target, key="schema", writer=_writer_of(target))
    return payload


def _writer_of(path: Path) -> object:
    """Return the version the provenance of a job names, ``None`` when it does not read."""
    try:
        provenance = read_document(path.with_name(JOB_PROVENANCE_FILENAME))
    except (OSError, ValueError):
        # The version is a hint of the refusal; an unreadable provenance leaves it unknown.
        return None
    tool = provenance.get("tool") if isinstance(provenance, Mapping) else None
    return tool.get("version") if isinstance(tool, Mapping) else None


__all__ = [
    "check_job_document",
    "read_document",
    "read_versioned",
    "render_document",
    "write_document",
]
