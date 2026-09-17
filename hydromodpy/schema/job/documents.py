"""How a job writes one of its documents: whole, or not at all.

Every document of a job directory is written through here, so a reader never
catches one half-written and the seal never hashes bytes that were still
being appended to. The rendering keeps the order the writing code chose,
because these files are read by people before they are read by programs; what
is canonicalised is what gets **hashed**, not what gets written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydromodpy.core.io.atomic_replace import rename_over_open_file


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


__all__ = ["read_document", "render_document", "write_document"]
