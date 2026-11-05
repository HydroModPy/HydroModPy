"""Finalization concerns for :class:`SimulationZarr`.

Owns lifecycle: write-lock acquisition, ``consolidate_metadata`` and
``close``. A run store is always a directory: there is no packed form,
and its content is exactly the Zarr hierarchy, so the write lock is
addressed outside of it, under the attempt state of the run that owns it
(see :func:`lock_path_for_store`).

All helpers take the live :class:`SimulationZarr` (or its store/lock)
explicitly so the module stays free of hidden global state.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zarr
from filelock import FileLock, Timeout

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUN_INTERNAL_LOCKS_DIRNAME

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)

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


class DummyLock:
    """No-op lock used for zip stores (read-only by construction)."""

    def acquire(self, *_: Any, **__: Any) -> None:
        return None

    def release(self) -> None:
        return None

    def __enter__(self) -> DummyLock:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def guard_write(lock: FileLock | DummyLock, path: Path) -> Any:
    """Return a context manager that holds the cross-process filelock."""
    if isinstance(lock, DummyLock):
        return lock
    try:
        return lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
    except Timeout as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Could not acquire Zarr write lock for {path} after {LOCK_TIMEOUT_SECONDS}s"
        ) from exc


def consolidate_metadata(store: Any, path: Path) -> None:
    """Consolidate Zarr metadata into a single ``.zmetadata`` entry."""
    if not isinstance(store, zarr.storage.LocalStore):
        return
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=(
                    "Consolidated metadata is currently not part .* Zarr format 3 specification.*"
                ),
                category=UserWarning,
            )
            zarr.consolidate_metadata(store)
    except Exception as exc:
        logger.warning("consolidate_metadata failed for %s: %s", path, exc)


def close(store_obj: SimulationZarr) -> None:
    """Close the live store and invoke any on-close callback."""
    if store_obj._store is not None:
        if hasattr(store_obj._store, "close"):
            store_obj._store.close()
        store_obj._store = None
    store_obj._root = None
    if store_obj._on_close is not None:
        callback = store_obj._on_close
        store_obj._on_close = None
        callback(store_obj)


__all__ = [
    "DummyLock",
    "LOCK_SUFFIX",
    "LOCK_TIMEOUT_SECONDS",
    "close",
    "consolidate_metadata",
    "guard_write",
    "lock_path_for_store",
]
