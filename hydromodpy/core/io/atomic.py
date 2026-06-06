"""Small atomic filesystem write helpers.

The public helpers here centralize the Windows-specific details that otherwise
get reimplemented as fragile ``tmp.write_text(...)`` + ``os.replace(...)``
snippets across the codebase.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from hydromodpy.core.io.filesystem import native_io_path


def atomic_write_text(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    fsync: bool = True,
) -> Path:
    """Write text to ``path`` via a sibling temp file and atomic promotion."""

    target = Path(path)
    os.makedirs(native_io_path(target.parent), exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp.{uuid.uuid4().hex}")
    tmp_io = native_io_path(tmp)
    target_io = native_io_path(target)
    try:
        with open(tmp_io, "w", encoding=encoding, newline=newline) as handle:
            handle.write(text)
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        replace_with_retry(tmp_io, target_io)
        if fsync:
            _fsync_parent_dir(target.parent)
    finally:
        try:
            os.unlink(tmp_io)
        except FileNotFoundError:
            pass
    return target


def atomic_write_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    ensure_ascii: bool = True,
) -> Path:
    """Serialize ``payload`` as JSON and write it atomically."""

    text = json.dumps(payload, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + "\n"
    return atomic_write_text(path, text)


def write_text_if_changed(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> bool:
    """Atomically write ``text`` only when it differs from the current file."""

    target = Path(path)
    try:
        with open(native_io_path(target), encoding=encoding, newline=newline) as handle:
            if handle.read() == text:
                return False
    except FileNotFoundError:
        pass
    atomic_write_text(target, text, encoding=encoding, newline=newline)
    return True


def replace_with_retry(source: str, target: str) -> None:
    """Promote ``source`` over ``target``, tolerating brief Windows locks."""

    attempts = 6 if os.name == "nt" else 1
    delay_s = 0.05
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)
            delay_s *= 2


def _fsync_parent_dir(parent: Path) -> None:
    """Best-effort directory fsync after atomic promotion."""

    try:
        dir_fd = os.open(native_io_path(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "replace_with_retry",
    "write_text_if_changed",
]
