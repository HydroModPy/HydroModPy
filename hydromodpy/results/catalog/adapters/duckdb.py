"""DuckDB adapter for :class:`CatalogBackend`.

Wraps a single :class:`duckdb.DuckDBPyConnection` so the catalog facade
keeps DuckDB-specific perf paths (``fetchdf``, ``register`` for in-memory
DataFrames) while exposing the backend-neutral surface of
:class:`~hydromodpy.results.catalog.ports.CatalogBackend`. ``INSERT`` and
``UPSERT`` are composed with ANSI syntax so the same call sites stay
portable across other adapters that implement the same protocol.

The adapter owns no schema state: ``ensure_schema`` delegates to the
catalog migration runner shipped in
:mod:`hydromodpy.results.catalog.migrations`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pandas as pd

from hydromodpy.core.io.db_retry import connect_with_retry
from hydromodpy.results.catalog.migrations import ensure_schema as _ensure_catalog_schema

if TYPE_CHECKING:
    pass


def _split_params(
    params: Sequence[Any] | dict[str, Any] | None,
) -> list[Any] | dict[str, Any] | None:
    """Return ``params`` in a shape DuckDB accepts as the second argument."""
    if params is None:
        return None
    if isinstance(params, dict):
        return params
    return list(params)


def _identifier(name: str) -> str:
    """Return ``name`` wrapped as a SQL identifier (double-quoted, escaped)."""
    if not name or not all(ch.isalnum() or ch == "_" for ch in name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


class DuckDBBackend:
    """Concrete :class:`CatalogBackend` backed by a DuckDB file connection.

    Two construction paths are supported. ``DuckDBBackend(path)`` opens a
    new connection on disk and owns it; ``DuckDBBackend.from_connection(c)``
    reuses an existing one and never closes it on the caller's behalf.

    Parameters
    ----------
    path
        Path to the ``catalog.duckdb`` file. When ``None``, ``connection``
        must be provided via :meth:`from_connection`.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._connection: duckdb.DuckDBPyConnection = connect_with_retry(str(self._path))
        self._owns_connection = True
        self._read_only = False

    @classmethod
    def from_connection(
        cls,
        connection: duckdb.DuckDBPyConnection,
        *,
        path: str | Path | None = None,
        read_only: bool = False,
    ) -> DuckDBBackend:
        """Wrap an existing DuckDB connection without taking ownership."""
        instance = cls.__new__(cls)
        instance._connection = connection
        instance._path = Path(path) if path is not None else Path("")
        instance._owns_connection = False
        instance._read_only = read_only
        return instance

    def _guard_writable(self) -> None:
        """Raise :class:`ReadOnlyError` when this backend is read-only."""
        if self._read_only:
            from hydromodpy.core.exceptions import ReadOnlyError

            raise ReadOnlyError(f"Catalog at {self._path} is open read-only; writes are refused.")

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Underlying DuckDB connection (escape hatch for perf paths)."""
        return self._connection

    @property
    def path(self) -> Path:
        """Path to the catalog file backing this adapter."""
        return self._path

    def ensure_schema(self) -> None:
        """Apply pending migrations from the catalog ``versions/`` directory."""
        _ensure_catalog_schema(self._connection)

    def query(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Execute a SELECT and return a :class:`pandas.DataFrame`."""
        bound = _split_params(params)
        cursor = (
            self._connection.execute(sql, bound)
            if bound is not None
            else (self._connection.execute(sql))
        )
        return cursor.fetchdf()

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> None:
        """Execute a DDL or DML statement and discard the result set."""
        self._guard_writable()
        bound = _split_params(params)
        if bound is None:
            self._connection.execute(sql)
        else:
            self._connection.execute(sql, bound)

    def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> tuple | None:
        """Execute a query and return one row or ``None``."""
        bound = _split_params(params)
        cursor = (
            self._connection.execute(sql, bound)
            if bound is not None
            else (self._connection.execute(sql))
        )
        row = cursor.fetchone()
        return tuple(row) if row is not None else None

    def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> list[tuple]:
        """Execute a query and return every row as a list of tuples."""
        bound = _split_params(params)
        cursor = (
            self._connection.execute(sql, bound)
            if bound is not None
            else (self._connection.execute(sql))
        )
        return [tuple(r) for r in cursor.fetchall()]

    def insert(self, table: str, row: dict[str, Any]) -> None:
        """Insert one row into ``table``.

        Builds ``INSERT INTO <table> (cols...) VALUES (?, ?, ...)`` with
        positional placeholders and identifier quoting. Portable across
        DuckDB and Postgres because no dialect feature is required.
        """
        self._guard_writable()
        if not row:
            raise ValueError("insert() requires a non-empty row mapping")
        tbl = _identifier(table)
        cols = [_identifier(c) for c in row.keys()]
        placeholders = ", ".join(["?"] * len(row))
        sql = f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({placeholders})"
        self._connection.execute(sql, list(row.values()))

    def upsert(
        self,
        table: str,
        row: dict[str, Any],
        *,
        key_cols: Sequence[str],
    ) -> None:
        """Insert or update on conflict over ``key_cols``.

        Composes ``INSERT INTO t (cols) VALUES (...) ON CONFLICT (keys)
        DO UPDATE SET col = EXCLUDED.col`` using ANSI syntax shared by
        DuckDB and Postgres. Updated columns are the non-key columns of
        ``row``.
        """
        self._guard_writable()
        if not row:
            raise ValueError("upsert() requires a non-empty row mapping")
        keys = list(key_cols)
        if not keys:
            raise ValueError("upsert() requires at least one key column")
        missing = [k for k in keys if k not in row]
        if missing:
            raise ValueError(f"upsert key columns missing from row: {missing}")
        tbl = _identifier(table)
        col_idents = [_identifier(c) for c in row.keys()]
        placeholders = ", ".join(["?"] * len(row))
        key_idents = ", ".join(_identifier(k) for k in keys)
        update_cols = [c for c in row.keys() if c not in keys]
        if update_cols:
            set_clause = ", ".join(
                f"{_identifier(c)} = EXCLUDED.{_identifier(c)}" for c in update_cols
            )
            sql = (
                f"INSERT INTO {tbl} ({', '.join(col_idents)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT ({key_idents}) DO UPDATE SET {set_clause}"
            )
        else:
            sql = (
                f"INSERT INTO {tbl} ({', '.join(col_idents)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT ({key_idents}) DO NOTHING"
            )
        self._connection.execute(sql, list(row.values()))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Open a transactional context with BEGIN/COMMIT/ROLLBACK.

        Rolls back and re-raises on any :class:`BaseException` (including
        :class:`KeyboardInterrupt`) so a Ctrl-C inside the block never leaves
        the connection wedged in an open transaction.
        """
        self._guard_writable()
        self._connection.execute("BEGIN TRANSACTION")
        try:
            yield
        except BaseException:
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

        DuckDB-specific helper used to federate the cache and catalog
        databases for cross-DB joins (``Run.input_entries``,
        ``DataEntry.used_by``). The alias is detached on exit, even on
        failure, so the connection state stays clean. ATTACH is not part
        of the ``CatalogBackend`` Protocol because the semantics differ
        widely across SQL engines; future Postgres-flavoured adapters
        will expose an equivalent via FDW or a dedicated helper.
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
        """Close the owned DuckDB connection. No-op if not owned."""
        if self._owns_connection:
            try:
                self._connection.close()
            except Exception:
                pass


__all__ = ["DuckDBBackend"]
