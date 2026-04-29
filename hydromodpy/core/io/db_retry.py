"""Retry decorator for DuckDB writes that may hit a file-level lock.

DuckDB opens the catalog file with a single-writer lock. When a concurrent
process is also open on the same file, the second caller raises
``duckdb.IOException`` with a message about a conflicting lock. We retry
with exponential backoff so short-lived contention (e.g. ``hmp list``
running while ``hmp run`` commits) resolves transparently.

Only ``duckdb.IOException`` is retried. Other exceptions propagate.
"""

from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from typing import TypeVar

import duckdb

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_RETRIES = 48
_DEFAULT_BACKOFF = 0.05
_DEFAULT_MAX_BACKOFF = 1.0
_LOCK_ERROR_SNIPPETS = (
    "conflicting lock",
    "another process",
    "autre processus",
    "resource temporarily unavailable",
    "database is locked",
)

F = TypeVar("F", bound=Callable[..., object])


def _is_lock_contention(exc: duckdb.IOException) -> bool:
    """Return whether ``exc`` looks like a transient DuckDB file-lock error."""
    message = str(exc).lower()
    return any(snippet in message for snippet in _LOCK_ERROR_SNIPPETS)


def _sleep_with_jitter(delay: float) -> float:
    """Sleep with a small positive jitter to desynchronise spawned workers."""
    sleep_for = delay * (1.0 + random.uniform(0.0, 0.25))
    time.sleep(sleep_for)
    return sleep_for


def connect_with_retry(
    db_path: str,
    *,
    retries: int = _DEFAULT_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
    max_backoff: float = _DEFAULT_MAX_BACKOFF,
    **kwargs: object,
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, retrying on file-lock contention.

    DuckDB acquires the per-file lock at ``connect()`` time. When several
    processes race to open the same catalog, the losers raise
    ``duckdb.IOException`` immediately - no built-in waiting. We loop with
    a capped exponential backoff so short-lived contention resolves
    transparently, including bursty ``spawn`` workloads on Windows.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return duckdb.connect(db_path, **kwargs)
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
