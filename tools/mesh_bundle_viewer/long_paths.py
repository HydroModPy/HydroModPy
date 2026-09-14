r"""Spell one path the way the Windows filesystem accepts past ``MAX_PATH``.

Without ``LongPathsEnabled``, Win32 refuses a path over 259 characters (247
for a directory) and the failure surfaces as ``WinError 3`` or ``WinError
206``, or silently as an empty listing. Prefixing the resolved path with
``\\?\`` lifts the cap for that one call, so every bundle read and every
artifact write in this package is spelled through :func:`filesystem_path`
first. On POSIX the path is returned unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path


def filesystem_path(path: Path) -> Path:
    """Return ``path`` spelled for the local filesystem API."""
    if os.name != "nt":
        return path
    text = str(Path(path).expanduser().resolve())
    if text.startswith("\\\\?\\"):
        return Path(text)
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text.lstrip("\\"))
    return Path("\\\\?\\" + text)


__all__ = ["filesystem_path"]
