"""The write-lock address and the metadata consolidation of a run store.

A run store is always a directory: there is no packed form, and its content
is exactly the Zarr hierarchy, so the write lock is addressed outside of it,
under the attempt state of the run that owns it (see
:func:`lock_path_for_store`).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import zarr

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUN_INTERNAL_LOCKS_DIRNAME

logger = get_logger(__name__)

# Zarr says that consolidated metadata is not part of the format 3 specification each
# time a store is consolidated or opened with it. Both are meant: readers need it.
warnings.filterwarnings(
    "ignore",
    message="Consolidated metadata is currently not part .* Zarr format 3 specification",
    category=UserWarning,
    module=r"zarr\.api\.asynchronous",
)

LOCK_TIMEOUT_SECONDS = 60.0
LOCK_SUFFIX = ".lock"


def lock_path_for_store(path: Path) -> Path:
    """Return the write-lock address of a store, always outside the store.

    A directory store is exactly its own content, so a lock file dropped
    inside it becomes a member of the Zarr hierarchy and of every content
    hash taken over it. The lock lives under ``.hmp/locks/`` of the directory
    that holds the store: for ``runs/<case>/fields.zarr`` that is the attempt
    state ``runs/<case>/.hmp/locks/``, removed with the rest of it when the
    run is sealed. Two stores of one directory never contend on one file
    because the lock is named after the store.
    """
    store = Path(path).resolve()
    return (
        store.parent / INTERNAL_DIRNAME / RUN_INTERNAL_LOCKS_DIRNAME / f"{store.name}{LOCK_SUFFIX}"
    )


def consolidate_metadata(store: Any, path: Path) -> None:
    """Consolidate Zarr metadata into a single ``.zmetadata`` entry."""
    if not isinstance(store, zarr.storage.LocalStore):
        return
    try:
        zarr.consolidate_metadata(store)
    except Exception as exc:
        logger.warning("consolidate_metadata failed for %s: %s", path, exc)


__all__ = [
    "LOCK_SUFFIX",
    "LOCK_TIMEOUT_SECONDS",
    "consolidate_metadata",
    "lock_path_for_store",
]
