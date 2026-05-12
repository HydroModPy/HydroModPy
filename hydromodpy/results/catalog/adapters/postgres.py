"""Postgres adapter stub for :class:`CatalogBackend`.

Lives in v2.0 as a placeholder so dependent code can already declare a
backend selection point. Every method raises ``NotImplementedError`` with
a stable message until the v2.x server work lands. The class satisfies
the :class:`CatalogBackend` Protocol structurally (it implements every
attribute by name and signature) so ``isinstance`` checks pass against
the ``runtime_checkable`` Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Any

import pandas as pd

_STUB_MESSAGE = "Postgres backend ready-to-go in v2.x, not implemented in v2.0"


class PostgresBackend:
    """Placeholder :class:`CatalogBackend` implementation for Postgres.

    Construction accepts a DSN so calling code can already wire the
    adapter into configuration. Every read or write raises
    ``NotImplementedError`` with :data:`_STUB_MESSAGE` until the v2.x
    server adapter ships.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @property
    def dsn(self) -> str:
        """Return the connection string supplied at construction."""
        return self._dsn

    def ensure_schema(self) -> None:
        raise NotImplementedError(_STUB_MESSAGE)

    def query(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError(_STUB_MESSAGE)

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError(_STUB_MESSAGE)

    def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> tuple | None:
        raise NotImplementedError(_STUB_MESSAGE)

    def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> list[tuple]:
        raise NotImplementedError(_STUB_MESSAGE)

    def insert(self, table: str, row: dict[str, Any]) -> None:
        raise NotImplementedError(_STUB_MESSAGE)

    def upsert(
        self,
        table: str,
        row: dict[str, Any],
        *,
        key_cols: Sequence[str],
    ) -> None:
        raise NotImplementedError(_STUB_MESSAGE)

    def transaction(self) -> AbstractContextManager[None]:
        raise NotImplementedError(_STUB_MESSAGE)

    def close(self) -> None:
        return None


__all__ = ["PostgresBackend"]
