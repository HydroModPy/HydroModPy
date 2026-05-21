"""DataCacheBackend Protocol skeleton.

Symmetric to :class:`hydromodpy.results.catalog.ports.CatalogBackend`.
This Protocol carves out the read/write surface of the data-side cache
catalog (today backed by DuckDB) so future swap-in backends (Postgres,
sqlite, in-memory for tests) can plug in without touching consumers.

This is a skeleton: T3 is responsible for wiring the existing
``DataCatalogDuckDB`` to this Protocol and migrating call sites. Adjust
the signatures against the concrete implementation when that wiring
lands; the names match the current public surface of
``DataCatalogDuckDB`` so the migration stays mechanical.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


class DataCacheBackend(Protocol):
    """Pluggable backend for the data-side cache catalog."""

    def register(
        self,
        *,
        variable: str,
        source: str,
        file_path: str | Path,
        station_id: str | None = None,
        bbox: tuple | None = None,
        crs: str | None = None,
        date_start: datetime | str | None = None,
        date_end: datetime | str | None = None,
        frequency: str | None = None,
        unit: str | None = None,
        source_unit: str | None = None,
        is_custom: bool = False,
        file_mtime: float | None = None,
        file_sha256: str | None = None,
        fetch_metadata: dict | None = None,
    ) -> int:
        """Register or update a data-file entry. Returns the entry id."""

    def find_cached(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None = None,
        bbox: tuple | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
    ) -> Any | None:
        """Return the cached entry covering the requested extent, or None."""

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Any:
        """List catalog entries as a DataFrame-like view."""

    def table_names(self) -> list[str]:
        """Return the list of tables present in the catalog."""

    def invalidate(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        station_id: str | None = None,
        delete_files: bool = False,
    ) -> int:
        """Remove matching entries. Returns count deleted."""

    def close(self) -> None:
        """Release the underlying connection."""


__all__ = ("DataCacheBackend",)
