"""Atomic JSON documents of a run, a session, a plan or a publication.

Why
---
Every JSON file a run directory carries is read by other processes while it
is being written: a launcher polling ``outcome.json``, an indexer reading
``manifest.json``, a watcher reading ``logs/heartbeat.json``. A reader must
see the previous document or the new one, never a truncated one. So every
document is written to a sibling temporary file and renamed onto its target
in one step.

Two writers, one difference
---------------------------
``write_json_atomic`` renames and stops: enough for a pulse or a ledger,
which the next write refreshes anyway. ``write_json_durable`` also calls
``fsync`` on the file before the rename and on the directory after it, so
the document survives a power cut. The seal (``manifest.json``) and the
issue (``outcome.json``) are durable; nothing else needs to be.

Format
------
Indented UTF-8 JSON, keys in the order the model dumped them, one trailing
newline. A payload is JSON-native already: models dump with
``model_dump(mode="json")`` before they reach this module, so there is no
``default=`` escape hatch and a value that cannot be rendered is a bug.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from hydromodpy.core.io.atomic_replace import rename_over_open_file


def render_json(payload: Any) -> str:
    """Render *payload* as the exact text a document carries."""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def read_json(path: str | Path) -> Any:
    """Read a document back."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stage(target: Path, payload: Any) -> Path:
    """Write *payload* to a temporary sibling of *target* and return it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    staged.write_text(render_json(payload), encoding="utf-8")
    return staged


def write_json_atomic(target: str | Path, payload: Any) -> Path:
    """Write *payload* to *target* through a temporary file and one rename."""
    path = Path(target)
    staged = _stage(path, payload)
    try:
        rename_over_open_file(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return path


def write_json_durable(target: str | Path, payload: Any) -> Path:
    """Write *payload* like :func:`write_json_atomic`, then make it survive a power cut.

    The staged bytes are flushed to the disk before the rename, and the
    directory entry after it, so neither the document nor its name can be
    lost once this returns.
    """
    path = Path(target)
    staged = _stage(path, payload)
    try:
        _fsync_file(staged)
        rename_over_open_file(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)
    return path


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(directory: Path) -> None:
    """Flush the directory entry; a no-op on Windows, which cannot open a directory."""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = ["read_json", "render_json", "write_json_atomic", "write_json_durable"]
