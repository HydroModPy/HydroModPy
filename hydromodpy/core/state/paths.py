"""XDG-compliant path helpers for HydroModPy.

Cache directory: binaries (solver downloads, http_cache).
State directory: index.duckdb, locks, audit.log.
Override env vars: HMP_CACHE_HOME, HMP_STATE_HOME, HMP_BIN.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

_APP_NAME = "hydromodpy"


def cache_dir() -> Path:
    """Return platform cache dir (HMP_CACHE_HOME override)."""
    override = os.environ.get("HMP_CACHE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_cache_dir(_APP_NAME))


def state_dir() -> Path:
    """Return platform state dir (HMP_STATE_HOME override)."""
    override = os.environ.get("HMP_STATE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_state_dir(_APP_NAME))


def bin_dir(solver: str, version: str) -> Path:
    """Return solver binary install path (HMP_BIN override)."""
    override = os.environ.get("HMP_BIN")
    if override:
        return Path(override).expanduser().resolve() / solver / version
    return cache_dir() / "bin" / solver / version


__all__ = ["bin_dir", "cache_dir", "state_dir"]
