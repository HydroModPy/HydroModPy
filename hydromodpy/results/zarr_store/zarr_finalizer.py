"""Finalization concerns for :class:`SimulationZarr`.

Owns lifecycle: write-lock acquisition, ``consolidate_metadata`` and
``close``. A run store is always a directory: there is no packed form,
and its content is exactly the Zarr hierarchy, so the write lock is
addressed outside of it (see :func:`lock_path_for_store`).

All helpers take the live :class:`SimulationZarr` (or its store/lock)
explicitly so the module stays free of hidden global state.
"""

from __future__ import annotations

import hashlib
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zarr
from filelock import FileLock, Timeout

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import internal_dir, resolve_project_root
from hydromodpy.results.zarr_store.zarr_schema import windows_long_path

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)

LOCK_TIMEOUT_SECONDS = 60.0
LOCKS_DIRNAME = "locks"
LOCK_KEY_LENGTH = 16


def lock_path_for_store(path: Path) -> Path:
    """Return the write-lock address of a store, always outside the store.

    A directory store is exactly its own content, so a lock file dropped
    inside it becomes a member of the Zarr hierarchy and of every content
    hash taken over it. POSIX keeps that file after release while Windows
    unlinks it, which would make the store bytes differ per platform. The
    lock lives in the disposable ``.hmp/locks`` directory of the owning
    project instead, keyed by the resolved store path so that two stores
    never contend on one file.
    """
    store = Path(path).resolve()
    key = hashlib.sha256(store.as_posix().encode("utf-8")).hexdigest()[:LOCK_KEY_LENGTH]
    locks_dir = internal_dir(resolve_project_root(store.parent)) / LOCKS_DIRNAME
    return locks_dir / f"{store.parent.name or store.name}-{key}.lock"


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


def drop_group(store_obj: SimulationZarr, name: str) -> int:
    """Delete a top-level group from a live directory store.

    Returns the number of bytes freed on disk (0 when the group is absent).
    """
    root = store_obj.root
    if name not in root:
        return 0
    if not store_obj._path.is_dir():
        raise RuntimeError(f"Cannot drop group '{name}' from a read-only store: {store_obj._path}")
    group_dir = windows_long_path(store_obj._path / name)
    freed = 0
    if group_dir.is_dir():
        freed = sum(f.stat().st_size for f in group_dir.rglob("*") if f.is_file())
    with guard_write(store_obj._lock, store_obj._path):
        del root[name]
    return freed


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
    "LOCKS_DIRNAME",
    "LOCK_KEY_LENGTH",
    "LOCK_TIMEOUT_SECONDS",
    "close",
    "consolidate_metadata",
    "drop_group",
    "guard_write",
    "lock_path_for_store",
]
