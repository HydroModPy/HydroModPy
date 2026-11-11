"""The file ``.hmp/index.duckdb``: its lock, its staging copy, its publication, its readers.

Why
---
This is the only module that creates, writes, publishes and opens the project
index. One process at a time writes it, under ``.hmp/index.duckdb.lock``
(:func:`index_lock`), a :class:`~hydromodpy.core.io.lock_file.LockFile` that
names its process, its host and its date. The lease lasts
:data:`INDEX_LEASE_S`; the indexer renews it every :data:`RENEW_EVERY`
entries, so a long pass keeps it and a dead one loses it.

The published file is never opened for writing. A reader holds it read-only
for as long as it likes (a ``Project`` holds it for its whole life), and
DuckDB refuses a writer on a file another process reads. So a pass writes a
staging file beside it (:func:`new_staging`, :func:`open_staging`) and moves
it over the published one in one rename (:func:`publish_staging`). A reader
that was open keeps the file it opened; the next opener gets the new one.

A new index is created in DuckDB blocks of 16 KiB
(:data:`~hydromodpy.core.io.db_retry.HMP_DUCKDB_BLOCK_SIZE`): the size holds at
about twice the minimum, 2.6 MB for 100 runs instead of 14.7 MB.

Readers open it with :func:`open_index`. The file is attached to a fresh
in-memory connection: a plain ``duckdb.connect`` on a path this process
already opened returns the database it opened then, even after a rename put
another file at that path, so a reader would not see what a pass published.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import duckdb

from hydromodpy.core.exceptions import CatalogUnreadableError, WriteConflictError
from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.core.io.db_retry import HMP_DUCKDB_BLOCK_SIZE, connect_with_retry
from hydromodpy.core.io.lock_file import LockFile, LockInfo
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import catalog_path_for

logger = get_logger(__name__)

INDEX_LOCK_NAME: Final = "index.duckdb.lock"
"""Name of the lock file, beside the index."""

INDEX_LEASE_S: Final = 600.0
"""Age past which the lock is stale. The writer renews it every :data:`RENEW_EVERY` entries."""

INDEX_WAIT_S: Final = 120.0
"""How long a pass waits for the lock before it gives up."""

RENEW_EVERY: Final = 100
"""Number of entries a writer handles between two renewals of its lease."""

INDEX_ALIAS: Final = "hmp_index"
"""Name under which :func:`open_index` attaches the index to its connection."""

_STAGING_COMPANIONS: Final = ("", ".wal", ".tmp")


def index_lock_path(project_root: Path | str) -> Path:
    """Return ``<project>/.hmp/index.duckdb.lock``."""
    return catalog_path_for(Path(project_root)).with_name(INDEX_LOCK_NAME)


def _holder_text(info: LockInfo | None) -> str:
    if info is None:
        return "another process"
    since = datetime.fromtimestamp(info.created, UTC).isoformat(timespec="seconds")
    return f"process {info.pid} on {info.host} since {since}"


@contextmanager
def index_lock(project_root: Path | str, *, wait_s: float = INDEX_WAIT_S) -> Iterator[LockFile]:
    """Hold the lock of the project index, and release it on the way out.

    Raises :class:`WriteConflictError` when another process keeps it past
    ``wait_s``. The lock is released on an exception too.
    """
    root = Path(project_root)
    lock = LockFile(index_lock_path(root), stale_after_s=INDEX_LEASE_S, wait_s=wait_s)
    if not lock.acquire():
        raise WriteConflictError(
            f"The index of {root} is being written by {_holder_text(lock.read())}. "
            f"Wait for it, or remove .hmp/{INDEX_LOCK_NAME} once that process is gone; "
            "the runs on disk are untouched.",
            project=str(root),
        )
    try:
        yield lock
    finally:
        lock.release()


def new_staging(index_path: Path, *, copy_of: Path | None) -> Path:
    """Create a staging file beside ``index_path`` and return its path.

    With ``copy_of``, the staging file is a copy of that file (an incremental
    pass starts from the published index). Without it, the staging file is a
    new empty database in blocks of 16 KiB.
    """
    staging = index_path.with_name(f"{index_path.name}.rebuild-{uuid4().hex[:8]}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        if copy_of is not None:
            shutil.copy2(copy_of, staging)
        else:
            connect_with_retry(str(staging), block_size=HMP_DUCKDB_BLOCK_SIZE).close()
    except BaseException:
        discard_staging(staging)
        raise
    return staging


def open_staging(staging: Path) -> duckdb.DuckDBPyConnection:
    """Open a staging file for writing. Never call it on the published index."""
    return connect_with_retry(str(staging))


def publish_staging(staging: Path, index_path: Path, lock: LockFile) -> None:
    """Move a finished staging file over the published index, in one rename.

    The lock is checked first: when another process took it while this one
    wrote, the staging file is not published and :class:`WriteConflictError`
    is raised. On Windows the rename works over a file a reader holds because
    DuckDB opens every database file with ``FILE_SHARE_DELETE`` from version
    1.5.0 on, and the floor of this package is ``duckdb>=1.5.2``. A rename the
    system refuses leaves the published index as it was and raises ``OSError``;
    the caller then drops the staging file with :func:`discard_staging`.
    """
    if not lock.still_held():
        raise WriteConflictError(
            f"The index at {index_path} was not published: another process took "
            f".hmp/{INDEX_LOCK_NAME} while this one wrote; the index it wrote is dropped.",
            index=str(index_path),
        )
    try:
        rename_over_open_file(staging, index_path)
    except OSError as refused:
        raise OSError(
            f"Could not publish the index at {index_path}: {refused}. "
            "The previous index is untouched and still readable; "
            "the next pass writes it again from the runs on disk."
        ) from refused
    _forget_write_ahead_log(index_path)


def discard_staging(staging: Path) -> None:
    """Remove a staging file and its companions; a missing one is no error."""
    for suffix in _STAGING_COMPANIONS:
        staging.with_name(f"{staging.name}{suffix}").unlink(missing_ok=True)


def open_index(project_root: Path | str) -> duckdb.DuckDBPyConnection:
    """Open the published index of a project, read-only.

    The connection sees the file as it stood when it was opened, whatever a
    pass publishes afterwards. Raises ``FileNotFoundError`` when the project
    has no index, and :class:`CatalogUnreadableError` when the file does not
    open as a DuckDB database.
    """
    index_path = catalog_path_for(Path(project_root))
    if not index_path.is_file():
        raise FileNotFoundError(f"{index_path} does not exist: the project has no index yet.")
    connection = connect_with_retry(":memory:")
    escaped = str(index_path).replace("'", "''")
    try:
        connection.execute(f"ATTACH '{escaped}' AS {INDEX_ALIAS} (READ_ONLY)")
        connection.execute(f"USE {INDEX_ALIAS}")
    except duckdb.Error as exc:
        connection.close()
        raise CatalogUnreadableError(str(index_path), reason=str(exc)) from exc
    return connection


def _forget_write_ahead_log(index_path: Path) -> None:
    """Drop the write-ahead log of the index that was just replaced."""
    wal_path = index_path.with_name(f"{index_path.name}.wal")
    try:
        wal_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Left the stale write-ahead log %s behind: %s", wal_path, exc)


__all__ = [
    "INDEX_ALIAS",
    "INDEX_LEASE_S",
    "INDEX_LOCK_NAME",
    "INDEX_WAIT_S",
    "RENEW_EVERY",
    "discard_staging",
    "index_lock",
    "index_lock_path",
    "new_staging",
    "open_index",
    "open_staging",
    "publish_staging",
]
