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
import logging
import time
from collections.abc import Callable
from typing import TypeVar

import duckdb

logger = logging.getLogger(__name__)

_DEFAULT_RETRIES = 8
_DEFAULT_BACKOFF = 0.05

F = TypeVar("F", bound=Callable[..., object])


def connect_with_retry(
    db_path: str,
    *,
    retries: int = _DEFAULT_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
    **kwargs: object,
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, retrying on file-lock contention.

    DuckDB acquires the per-file lock at ``connect()`` time. When several
    processes race to open the same catalog, the losers raise
    ``duckdb.IOException`` immediately - no built-in waiting. We loop with
    exponential backoff so short-lived contention resolves transparently.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return duckdb.connect(db_path, **kwargs)
        except duckdb.IOException as exc:
            last_exc = exc
            if attempt == retries - 1:
                break
            delay = backoff * (2**attempt)
            logger.debug(
                "DuckDB connect contention on %s, retry %d/%d in %.2fs",
                db_path,
                attempt + 1,
                retries,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def with_lock_retry(
    *,
    retries: int = _DEFAULT_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
) -> Callable[[F], F]:
    """Retry a method that may raise ``duckdb.IOException`` on file lock.

    ``retries`` is the total number of attempts including the first one.
    ``backoff`` is the base delay in seconds; each attempt waits
    ``backoff * 2**attempt`` before the next try.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            last_exc: Exception | None = None
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except duckdb.IOException as exc:
                    last_exc = exc
                    if attempt == retries - 1:
                        break
                    delay = backoff * (2**attempt)
                    logger.debug(
                        "DuckDB lock contention on %s, retry %d/%d in %.2fs",
                        func.__name__,
                        attempt + 1,
                        retries,
                        delay,
                    )
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
