"""Single open point for every DuckDB file HydroModPy owns.

DuckDB opens the catalog file with a single-writer lock. When a concurrent
process is also open on the same file, the second caller raises
``duckdb.IOException`` with a message about a conflicting lock. We retry
with exponential backoff so short-lived contention (e.g. ``hmp list``
running while ``hmp run`` commits) resolves transparently.

Only ``duckdb.IOException`` is retried. Other exceptions propagate.

The open is also where a write-ahead log left by an unclean shutdown is
checkpointed back into the database file (see :func:`_absorb_stale_wal`).
"""

from __future__ import annotations

import functools
import random
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import duckdb

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_RETRIES = 48
_DEFAULT_BACKOFF = 0.05
_DEFAULT_MAX_BACKOFF = 1.0

# DuckDB defaults to 256 KiB blocks, which bloats a small many-table metadata
# database (a fresh catalog needs one block per table minimum). 16 KiB is the
# DuckDB minimum and cuts the on-disk footprint several-fold. block_size is
# immutable after file creation, so it can only be set when the file is created.
HMP_DUCKDB_BLOCK_SIZE = 16384
# Databases this process has already inspected for a left-over write-ahead log.
_WAL_SEEN_PATHS: set[str] = set()
_WAL_SEEN_LOCK = threading.Lock()
_LOCK_ERROR_SNIPPETS = (
    "conflicting lock",
    "another process",
    "autre processus",
    "resource temporarily unavailable",
    "database is locked",
)
# DuckDB refuses to attach a file another database in this process already
# holds, and says so in its own English wording whatever the OS locale is.
_ATTACH_CONFLICT_SNIPPETS = (
    "unique file handle conflict",
    "already attached",
)

F = TypeVar("F", bound=Callable[..., object])


def _is_lock_contention(exc: duckdb.IOException) -> bool:
    """Return whether ``exc`` looks like a transient DuckDB file-lock error."""
    message = str(exc).lower()
    return any(snippet in message for snippet in _LOCK_ERROR_SNIPPETS)


def _is_attach_path_conflict(exc: duckdb.BinderException) -> bool:
    """Return whether ``exc`` says this process already holds that database file."""
    message = str(exc).lower()
    return any(snippet in message for snippet in _ATTACH_CONFLICT_SNIPPETS)


def _sleep_with_jitter(delay: float) -> float:
    """Sleep with a small positive jitter to desynchronise spawned workers."""
    sleep_for = delay * (1.0 + random.uniform(0.0, 0.25))
    time.sleep(sleep_for)
    return sleep_for


def _stale_wal_size(db_path: str) -> int | None:
    """Return the size of a write-ahead log left by a dead process, or None.

    Only the first open of a database in this process can tell a journal
    abandoned by a previous process from one a live sibling connection is
    still filling, so later opens of the same file report nothing.
    """
    if db_path == ":memory:" or not db_path:
        return None
    key = str(Path(db_path).absolute())
    with _WAL_SEEN_LOCK:
        if key in _WAL_SEEN_PATHS:
            return None
        _WAL_SEEN_PATHS.add(key)
    try:
        return Path(f"{db_path}.wal").stat().st_size
    except OSError:
        return None


def _absorb_stale_wal(
    connection: duckdb.DuckDBPyConnection,
    db_path: str,
    wal_bytes: int,
) -> None:
    """Fold a write-ahead log left by an unclean exit back into the database.

    DuckDB journals committed transactions into ``<db>.wal`` and only absorbs
    them at a clean close. A process killed by an uncatchable signal leaves the
    file behind: every later open has to replay it, the replay is what breaks
    the ART indexes of a torn journal, and any tool that copies the database
    file alone silently drops the rows the journal still holds. Opening for
    writing is the one moment able to settle it, so settle it once, loudly.
    """
    try:
        connection.execute("CHECKPOINT")
    except duckdb.Error as exc:
        logger.warning(
            "Left-over DuckDB write-ahead log on %s (%.1f KiB) could not be checkpointed: %s",
            db_path,
            wal_bytes / 1024.0,
            exc,
        )
        return
    logger.warning(
        "Recovered a left-over DuckDB write-ahead log on %s (%.1f KiB): "
        "checkpointed at open after an unclean shutdown.",
        db_path,
        wal_bytes / 1024.0,
    )


def _precreate_with_block_size(db_path: str, block_size: int) -> None:
    """Materialise a new DuckDB file with ``block_size`` before the real open.

    ATTACHes the not-yet-existing file with the requested block size and
    checkpoints so the header records it; subsequent plain ``connect()`` calls
    then inherit it (block_size is immutable once the file exists).

    DuckDB registers attached database files process-wide, and the entry
    outlives the file: a connection still open on a path someone deleted keeps
    that path claimed although it is gone from disk. Sizing blocks is a
    footprint optimisation, never a reason to refuse a connection, so that one
    conflict is skipped and the caller falls through to a plain open. Every
    other failure propagates.
    """
    escaped = db_path.replace("'", "''")
    tmp = duckdb.connect(":memory:")
    try:
        tmp.execute(f"ATTACH '{escaped}' (BLOCK_SIZE {int(block_size)})")
        tmp.execute("CHECKPOINT")
    except duckdb.BinderException as exc:
        if not _is_attach_path_conflict(exc):
            raise
        logger.debug(
            "Skipping the DuckDB block-size pre-create on %s, the path is still "
            "attached in this process: %s",
            db_path,
            exc,
        )
    finally:
        tmp.close()


def connect_with_retry(
    db_path: str,
    *,
    retries: int = _DEFAULT_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
    max_backoff: float = _DEFAULT_MAX_BACKOFF,
    block_size: int | None = None,
    **kwargs: object,
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, retrying on file-lock contention.

    DuckDB acquires the per-file lock at ``connect()`` time. When several
    processes race to open the same catalog, the losers raise
    ``duckdb.IOException`` immediately - no built-in waiting. We loop with
    a capped exponential backoff so short-lived contention resolves
    transparently, including bursty ``spawn`` workloads on Windows.

    ``block_size`` pre-creates a not-yet-existing read-write file with that
    DuckDB block size (see :data:`HMP_DUCKDB_BLOCK_SIZE`) to keep small metadata
    databases compact. That pre-create is best effort: it never decides whether
    the connection can be opened.

    A write-ahead log left behind by an unclean shutdown is checkpointed on the
    first read-write open (see :func:`_absorb_stale_wal`).
    """
    writable = not kwargs.get("read_only")
    if block_size is not None and db_path != ":memory:" and writable and not Path(db_path).exists():
        _precreate_with_block_size(db_path, block_size)

    wal_bytes = _stale_wal_size(db_path) if writable else None

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            connection = duckdb.connect(db_path, **kwargs)
            if wal_bytes is not None:
                _absorb_stale_wal(connection, db_path, wal_bytes)
            return connection
        except duckdb.IOException as exc:
            if not _is_lock_contention(exc):
                raise
            last_exc = exc
            if attempt == retries - 1:
                break
            delay = min(backoff * (2**attempt), max_backoff)
            sleep_for = _sleep_with_jitter(delay)
            logger.debug(
                "DuckDB connect contention on %s, retry %d/%d in %.2fs",
                db_path,
                attempt + 1,
                retries,
                sleep_for,
            )
    assert last_exc is not None
    raise last_exc


def with_lock_retry(
    *,
    retries: int = _DEFAULT_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
    max_backoff: float = _DEFAULT_MAX_BACKOFF,
) -> Callable[[F], F]:
    """Retry a method that may raise ``duckdb.IOException`` on file lock.

    ``retries`` is the total number of attempts including the first one.
    ``backoff`` is the base delay in seconds; each attempt waits
    ``min(backoff * 2**attempt, max_backoff)`` before the next try.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            last_exc: Exception | None = None
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except duckdb.IOException as exc:
                    if not _is_lock_contention(exc):
                        raise
                    last_exc = exc
                    if attempt == retries - 1:
                        break
                    delay = min(backoff * (2**attempt), max_backoff)
                    sleep_for = _sleep_with_jitter(delay)
                    logger.debug(
                        "DuckDB lock contention on %s, retry %d/%d in %.2fs",
                        func.__name__,
                        attempt + 1,
                        retries,
                        sleep_for,
                    )
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
