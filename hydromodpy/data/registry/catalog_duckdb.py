"""Data catalog backed by DuckDB.

Thin facade over the three concern modules:

- :mod:`cache_store`: connection management, schema bootstrap, ``register``,
  frozen-mode helpers.
- :mod:`cache_queries`: read-only lookups (``find_cached``, ``list_entries``,
  ``table_names``).
- :mod:`cache_lifecycle`: destructive ops and sidecar inserters.

``DataCatalogDuckDB`` keeps a stable public API: every method that used to
live here is still callable from the same import path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from upath import UPath

from hydromodpy.core.io.db_retry import HMP_DUCKDB_BLOCK_SIZE, connect_with_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.data.registry import cache_lifecycle, cache_queries, cache_store
from hydromodpy.data.registry.backend import CacheBackend, DuckDBCacheBackend
from hydromodpy.data.registry.cache_queries import CatalogEntry as _CatalogEntry
from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY
from hydromodpy.data.registry.migrations import ensure_schema as _ensure_cache_schema

logger = get_logger(__name__)

__all__ = [
    "DataCatalogDuckDB",
    "SENTINEL_CUSTOM",
    "SENTINEL_EMPTY",
]


class DataCatalogDuckDB:
    """DuckDB-backed data catalog."""

    def __init__(self, db_path: Path | UPath | str | None = None):
        self._db_path: Path | None = None
        if db_path is None:
            self._conn = duckdb.connect(":memory:")
        else:
            db_path = Path(str(db_path))
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = db_path
            self._conn = connect_with_retry(str(db_path), block_size=HMP_DUCKDB_BLOCK_SIZE)

        _ensure_cache_schema(self._conn)
        self._backend: CacheBackend = DuckDBCacheBackend.from_connection(
            self._conn, path=self._db_path
        )

    @property
    def connection(self):
        """Underlying DuckDB connection (advanced usage)."""
        return self._conn

    @property
    def backend(self) -> CacheBackend:
        """SQL-level backend port driving cache reads and writes."""
        return self._backend

    def close(self) -> None:
        self._backend.close()
        self._conn.close()

    def __enter__(self) -> DataCatalogDuckDB:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # -- store helpers ---------------------------------------------------------

    def _workspace_root(self) -> Path | None:
        return cache_store.workspace_root(self)

    def _encode_path_for_storage(self, file_path: Path | str) -> str:
        return cache_store.encode_path_for_storage(self, file_path)

    def _resolve_entry_path(self, file_path: Path | str, *, variable: str | None = None) -> Path:
        return cache_store.resolve_entry_path(self, file_path, variable=variable)

    def _workspace_lockfile_path(self) -> Path | None:
        return cache_store.workspace_lockfile_path(self)

    @staticmethod
    def _frozen_enabled() -> bool:
        return cache_store.frozen_enabled()

    def _locked_artifacts(self):
        return cache_store.locked_artifacts(self)

    def _match_locked_artifact(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None,
        file_path: Path | str,
    ):
        return cache_store.match_locked_artifact(
            self,
            variable=variable,
            source=source,
            station_id=station_id,
            file_path=file_path,
        )

    def _reject_frozen_cache_miss(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None,
    ) -> None:
        cache_store.reject_frozen_cache_miss(
            self,
            variable=variable,
            source=source,
            station_id=station_id,
        )

    def _reject_frozen_entry_mismatch(self, entry: _CatalogEntry) -> None:
        cache_store.reject_frozen_entry_mismatch(self, entry)

    def _reject_frozen_register(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None,
        file_path: Path,
        file_sha256: str | None,
        is_custom: bool,
    ) -> None:
        cache_store.reject_frozen_register(
            self,
            variable=variable,
            source=source,
            station_id=station_id,
            file_path=file_path,
            file_sha256=file_sha256,
            is_custom=is_custom,
        )

    # -- register --------------------------------------------------------------

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
        """Register or update a data file entry. Returns entry id (-1 on error)."""
        return cache_store.register(
            self,
            variable=variable,
            source=source,
            file_path=file_path,
            station_id=station_id,
            bbox=bbox,
            crs=crs,
            date_start=date_start,
            date_end=date_end,
            frequency=frequency,
            unit=unit,
            source_unit=source_unit,
            is_custom=is_custom,
            file_mtime=file_mtime,
            file_sha256=file_sha256,
            fetch_metadata=fetch_metadata,
        )

    # -- queries ---------------------------------------------------------------

    def find_cached(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None = None,
        bbox: tuple | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
    ) -> _CatalogEntry | None:
        """Find a cached entry covering the requested extent/period (superset)."""
        return cache_queries.find_cached(
            self,
            variable=variable,
            source=source,
            station_id=station_id,
            bbox=bbox,
            date_start=date_start,
            date_end=date_end,
        )

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> pd.DataFrame:
        """List catalog entries as a DataFrame."""
        return cache_queries.list_entries(
            self,
            variable=variable,
            source=source,
            limit=limit,
            offset=offset,
        )

    def table_names(self) -> list[str]:
        """Return the list of tables present in the catalog."""
        return cache_queries.table_names(self)

    # -- lifecycle: destructive ops --------------------------------------------

    def invalidate(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        station_id: str | None = None,
        delete_files: bool = False,
    ) -> int:
        """Remove matching entries. Returns count deleted."""
        return cache_lifecycle.invalidate(
            self,
            variable=variable,
            source=source,
            station_id=station_id,
            delete_files=delete_files,
        )

    def subsume_entries(
        self,
        *,
        variable: str,
        source: str,
        bbox: tuple,
        date_start: str | None,
        date_end: str | None,
        exclude_id: int | None = None,
    ) -> int:
        """Delete grid entries fully contained within the given bbox+dates."""
        return cache_lifecycle.subsume_entries(
            self,
            variable=variable,
            source=source,
            bbox=bbox,
            date_start=date_start,
            date_end=date_end,
            exclude_id=exclude_id,
        )

    def prune_older_than(
        self,
        *,
        days: int,
        delete_files: bool = False,
    ) -> int:
        """Delete cache entries older than *days* days. Returns count removed."""
        return cache_lifecycle.prune_older_than(
            self,
            days=days,
            delete_files=delete_files,
        )

    def check_and_fix(self) -> dict[str, int]:
        """Scan entries and attempt to repair inconsistencies."""
        return cache_lifecycle.check_and_fix(self)

    def cleanup(self) -> int:
        """Remove entries whose files no longer exist on disk."""
        return cache_lifecycle.cleanup(self)

    # -- lifecycle: sidecar inserters ------------------------------------------

    def write_artifact(
        self,
        *,
        artifact_type: str,
        path: str | Path,
        sha256: str | None = None,
        size_bytes: int | None = None,
        sim_id: str | None = None,
        variable: str | None = None,
    ) -> int:
        """Record an artifact row; returns its id."""
        return cache_lifecycle.write_artifact(
            self,
            artifact_type=artifact_type,
            path=path,
            sha256=sha256,
            size_bytes=size_bytes,
            sim_id=sim_id,
            variable=variable,
        )

    def write_provenance(
        self,
        *,
        artifact_id: int | None = None,
        variable: str | None = None,
        source: str | None = None,
        input_hash: str | None = None,
        tool_name: str | None = None,
        tool_version: str | None = None,
        parameters: dict | None = None,
    ) -> int:
        """Record a provenance row; returns its id."""
        return cache_lifecycle.write_provenance(
            self,
            artifact_id=artifact_id,
            variable=variable,
            source=source,
            input_hash=input_hash,
            tool_name=tool_name,
            tool_version=tool_version,
            parameters=parameters,
        )

    def upsert_station(
        self,
        *,
        station_id: str,
        variable: str,
        source: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        z: float | None = None,
        name: str | None = None,
        first_valid: str | None = None,
        last_valid: str | None = None,
    ) -> None:
        """Insert or update a station metadata row."""
        cache_lifecycle.upsert_station(
            self,
            station_id=station_id,
            variable=variable,
            source=source,
            lat=lat,
            lon=lon,
            z=z,
            name=name,
            first_valid=first_valid,
            last_valid=last_valid,
        )

    def write_coverage(
        self,
        *,
        variable: str,
        source: str | None = None,
        region_wkt: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        n_stations: int | None = None,
    ) -> int:
        """Record a coverage row; returns its id."""
        return cache_lifecycle.write_coverage(
            self,
            variable=variable,
            source=source,
            region_wkt=region_wkt,
            period_start=period_start,
            period_end=period_end,
            n_stations=n_stations,
        )

    def write_failure(
        self,
        *,
        variable: str | None = None,
        source_ref: str | None = None,
        error_type: str,
        message: str | None = None,
    ) -> int:
        """Record a failure row; returns its id."""
        return cache_lifecycle.write_failure(
            self,
            variable=variable,
            source_ref=source_ref,
            error_type=error_type,
            message=message,
        )

    def write_validation_report(
        self,
        *,
        schema_name: str,
        passed: bool,
        artifact_id: int | None = None,
        errors: list | dict | None = None,
    ) -> int:
        """Record a validation report; returns its id."""
        return cache_lifecycle.write_validation_report(
            self,
            schema_name=schema_name,
            passed=passed,
            artifact_id=artifact_id,
            errors=errors,
        )
