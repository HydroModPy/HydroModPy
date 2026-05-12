"""Storage backend Protocol for the catalog.

Defines a structural contract that the catalog facade depends on. Adapters
live next to it under ``adapters/`` and stay free to use SQLAlchemy 2.0
Core, a direct DuckDB connection, or any other driver as long as the
Protocol surface is preserved.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class CatalogBackend(Protocol):
    """Storage backend port for the catalog.

    The catalog facade interacts with the SQL store only through this
    surface. ``DuckDBBackend`` is the default v2.0 implementation;
    ``PostgresBackend`` is a stub kept as a structural placeholder for
    v2.x. Every method maps to a single round-trip with the underlying
    driver and never silently swallows exceptions.
    """

    def ensure_schema(self) -> None:
        """Run the migration runner to deploy the catalog v2 schema."""

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

    def insert(self, table: str, row: dict[str, Any]) -> None:
        """Insert one row in ``table`` mapping column names to values."""

    def upsert(
        self,
        table: str,
        row: dict[str, Any],
        *,
        key_cols: Sequence[str],
    ) -> None:
        """Insert or update on conflict over ``key_cols``."""

    def transaction(self) -> AbstractContextManager[None]:
        """Open a transactional context (BEGIN/COMMIT/ROLLBACK)."""

    def close(self) -> None:
        """Release any held connection or engine resources."""


__all__ = ["CatalogBackend"]
