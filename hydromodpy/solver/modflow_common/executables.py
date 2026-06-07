"""Helpers for bundled solver executables across platforms."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def ensure_platform_executable(path: str | Path) -> Path:
    """Ensure one bundled solver binary is executable on POSIX checkouts."""
    executable = Path(path)
    if os.name == "nt" or not executable.is_file():
        return executable

    try:
        current_mode = executable.stat().st_mode
    except OSError:
        return executable

    execute_bits = 0
    if current_mode & stat.S_IRUSR:
        execute_bits |= stat.S_IXUSR
    if current_mode & stat.S_IRGRP:
        execute_bits |= stat.S_IXGRP
    if current_mode & stat.S_IROTH:
        execute_bits |= stat.S_IXOTH

    if execute_bits == 0 or (current_mode & execute_bits) == execute_bits:
        return executable

    try:
        executable.chmod(current_mode | execute_bits)
    except OSError:
        return executable
    return executable


__all__ = ["ensure_platform_executable"]
