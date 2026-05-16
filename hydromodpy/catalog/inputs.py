"""Workspace-scoped inputs namespace -- wraps ``data/cache.duckdb``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

_DATA_CACHE_BASENAME = "cache.duckdb"


class InputsNamespace:
    """Read-mostly facade over ``<workspace>/data/cache.duckdb``.

    Lazily opens a :class:`~hydromodpy.data.registry.DataCatalogDuckDB`
    on first call.
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace).expanduser().resolve()
        self._catalog: Any = None

    @property
    def db_path(self) -> Path:
        """Filesystem path of the underlying cache DuckDB."""
        return self._workspace / "data" / _DATA_CACHE_BASENAME

    def has_cache(self) -> bool:
        """Return ``True`` when ``<workspace>/data/cache.duckdb`` exists."""
        return self.db_path.is_file()

    def _open(self) -> Any:
        if self._catalog is None:
            from hydromodpy.data.registry import DataCatalogDuckDB

            self._catalog = DataCatalogDuckDB(self.db_path)
        return self._catalog

    def list(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """List cache entries, optionally filtered by ``variable``/``source``."""
        return self._open().list_entries(variable=variable, source=source, limit=limit)

    def find(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None = None,
        bbox: tuple | None = None,
    ) -> Any:
        """Return the cached entry covering the requested extent, or ``None``."""
        return self._open().find_cached(
            variable=variable, source=source, station_id=station_id, bbox=bbox
        )

    def close(self) -> None:
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None


__all__ = ["InputsNamespace"]
