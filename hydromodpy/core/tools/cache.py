"""Platform-specific user cache directory for HydroModPy.

The cache is used for downloaded solver binaries, HELP3O Fortran
extensions, and any other runtime assets that we fetch lazily rather
than ship inside the wheel. Layout::

    Linux    ~/.cache/hydromodpy/
    macOS    ~/Library/Caches/hydromodpy/
    Windows  %LOCALAPPDATA%\\hydromodpy\\

Subdirectories (``bin/`` for solver exes, etc.) are created on demand by
the callers.
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_cache_dir() -> Path:
    """Return the root HydroModPy cache directory, creating it if needed."""
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "hydromodpy"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "hydromodpy"
    else:
        base = Path.home() / ".cache" / "hydromodpy"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_cache_bin_dir() -> Path:
    """Return the subdirectory where downloaded solver binaries live."""
    bin_dir = get_cache_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return bin_dir


__all__ = ["get_cache_dir", "get_cache_bin_dir"]
