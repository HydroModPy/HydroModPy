"""DuckDB SQL-level adapter for the data-side cache catalog.

This module hosts ``DuckDBCacheBackend``, the SQL adapter that mirrors
:class:`hydromodpy.results.catalog.adapters.duckdb.DuckDBBackend` but
targets the workspace-level data cache rather than the project-level
results catalog.

Two layers coexist:

- ``hydromodpy.core.contracts.data_cache_backend.DataCacheBackend``: the
  high-level "Store" Protocol exposing ``register``, ``find_cached`` etc.
  ``DataCatalogDuckDB`` implements this surface and stays the entry
  point for consumers.
- ``CacheBackend`` (this module): the SQL-level Protocol used internally
  by ``cache_store`` / ``cache_queries`` / ``cache_lifecycle`` so the
  three modules never reach for ``catalog._conn`` directly.

The split keeps T5's high-level Protocol stable while T3 finishes the
port-driven refactor on the SQL plumbing.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import duckdb
import pandas as pd

from hydromodpy.core.io.db_retry import connect_with_retry


@runtime_checkable
class CacheBackend(Protocol):
    """SQL-level backend for the data cache catalog.

    Mirrors the surface of
    :class:`hydromodpy.results.catalog.ports.CatalogBackend` so the same
    consumers can be templated across the two catalogs in the future.
    """

    def query(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Execute a SELECT and return a :class:`pandas.DataFrame`."""

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> None:
        """Execute a DDL or DML statement and discard the result set."""

    def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> tuple | None:
        """Execute a query and return one row tuple or ``None``."""

    def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> list[tuple]:
        """Execute a query and return every row as a list of tuples."""

    def description(self) -> list[tuple[str, str]] | None:
        """Return (name, type) for the columns of the last executed query."""

    def transaction(self) -> AbstractContextManager[None]:
        """Open a transactional context (BEGIN/COMMIT/ROLLBACK)."""

    def close(self) -> None:
        """Release any held connection or engine resources."""


def _split_params(
    params: Sequence[Any] | dict[str, Any] | None,
) -> list[Any] | dict[str, Any] | None:
    """Return ``params`` in a shape DuckDB accepts as the second argument."""
    if params is None:
        return None
    if isinstance(params, dict):
        return params
    return list(params)


class DuckDBCacheBackend:
    """Concrete :class:`CacheBackend` backed by a DuckDB file connection.

    Two construction paths are supported. ``DuckDBCacheBackend(path)``
    opens a new connection on disk and owns it;
    ``DuckDBCacheBackend.from_connection(c)`` wraps an existing
    connection and never closes it on the caller's behalf.
    """

    def __init__(self, path: str | Path) -> None:
        self._path: Path | None = Path(path)
        self._connection: duckdb.DuckDBPyConnection = connect_with_retry(str(self._path))
        self._owns_connection = True
        self._last_description: list[tuple[str, str]] | None = None

    @classmethod
    def from_connection(
        cls,
        connection: duckdb.DuckDBPyConnection,
        *,
        path: str | Path | None = None,
    ) -> DuckDBCacheBackend:
        """Wrap an existing DuckDB connection without taking ownership."""
        instance = cls.__new__(cls)
        instance._connection = connection
        instance._path = Path(path) if path is not None else None
        instance._owns_connection = False
        instance._last_description = None
        return instance

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Underlying DuckDB connection (escape hatch for perf paths)."""
        return self._connection

    @property
    def path(self) -> Path | None:
        """Path to the cache file backing this adapter, or None for in-memory."""
        return self._path

    def _capture_description(self, cursor: Any) -> None:
        desc = getattr(cursor, "description", None)
        if desc is None:
            self._last_description = None
            return
        self._last_description = [(d[0], str(d[1]) if d[1] is not None else "") for d in desc]

    def query(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        bound = _split_params(params)
        cursor = (
            self._connection.execute(sql, bound)
            if bound is not None
            else self._connection.execute(sql)
        )
        self._capture_description(cursor)
        return cursor.fetchdf()

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> None:
        bound = _split_params(params)
        if bound is None:
            self._connection.execute(sql)
        else:
            self._connection.execute(sql, bound)
        self._last_description = None

    def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> tuple | None:
        bound = _split_params(params)
        cursor = (
            self._connection.execute(sql, bound)
            if bound is not None
            else self._connection.execute(sql)
        )
        self._capture_description(cursor)
        row = cursor.fetchone()
        return tuple(row) if row is not None else None

    def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> list[tuple]:
        bound = _split_params(params)
        cursor = (
            self._connection.execute(sql, bound)
            if bound is not None
            else self._connection.execute(sql)
        )
        self._capture_description(cursor)
        return [tuple(r) for r in cursor.fetchall()]

    def description(self) -> list[tuple[str, str]] | None:
        return self._last_description

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN TRANSACTION")
        try:
            yield
        except Exception:
            try:
                self._connection.execute("ROLLBACK")
            except Exception:
                pass
            raise
        else:
            self._connection.execute("COMMIT")

    @contextmanager
    def attach_read_only(self, db_path: str | Path, alias: str) -> Iterator[None]:
        """ATTACH ``db_path`` in read-only mode under ``alias`` for the block.

        Mirror of the helper on the catalog-side DuckDB adapter so the
        cache can federate with a project catalog DB for cross-DB joins
        (``DataEntry.used_by``).
        """
        if not all(ch.isalnum() or ch == "_" for ch in alias):
            raise ValueError(f"Invalid attach alias: {alias!r}")
        path_str = str(Path(db_path))
        path_literal = path_str.replace("'", "''")
        self._connection.execute(f"ATTACH '{path_literal}' AS {alias} (READ_ONLY)")
        try:
            yield
        finally:
            try:
                self._connection.execute(f"DETACH {alias}")
            except Exception:
                pass

    def close(self) -> None:
        if self._owns_connection:
            try:
                self._connection.close()
            except Exception:
                pass


__all__ = ["CacheBackend", "DuckDBCacheBackend"]
