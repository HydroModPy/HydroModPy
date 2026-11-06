"""Data catalog backed by DuckDB.

Thin facade over the three concern modules:

- :mod:`cache_store`: connection management, schema bootstrap, ``register``,
  frozen-mode helpers.
- :mod:`cache_queries`: read-only lookups (``find_cached``, ``list_entries``,
  ``table_names``).
- :mod:`cache_lifecycle`: destructive ops and sidecar inserters.

Three ways to open the workspace cache
--------------------------------------
- Read-write, the default: the process owns the file while it is open. One
  process at a time can do this.
- Read-only (``read_only=True``): many processes can read together, and
  nothing is written. ``hmp data`` reads and the ``--frozen`` check open the
  cache this way.
- Layered, inside a case started by the launcher: the environment names a
  private cache (:data:`PRIVATE_CACHE_ENV`). Every write and every lookup a
  write needs goes to the private file; a read query asks the shared cache
  first, opened read-only for that one query and closed at once, then the
  private file. The shared file is never held open, so the launcher can
  merge a finished case (:func:`merge_private_cache`) while other cases run.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from upath import UPath

from hydromodpy.core.io.db_retry import HMP_DUCKDB_BLOCK_SIZE, connect_with_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.data.registry import cache_lifecycle, cache_queries, cache_store
from hydromodpy.data.registry.backend import CacheBackend, DuckDBCacheBackend
from hydromodpy.data.registry.cache_queries import CatalogEntry
from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY
from hydromodpy.data.registry.migrations.auto_boot import ensure_schema_safe

logger = get_logger(__name__)

PRIVATE_CACHE_ENV = "HMP_DATA_CACHE_PRIVATE"
"""Private data cache of a launched case; set, the shared cache is read-only."""

__all__ = [
    "PRIVATE_CACHE_ENV",
    "DataCatalogDuckDB",
    "SENTINEL_CUSTOM",
    "SENTINEL_EMPTY",
    "merge_private_cache",
    "private_cache_path",
]


def private_cache_path() -> Path | None:
    """Return the private cache the environment names, or ``None`` outside a launched case."""
    text = os.environ.get(PRIVATE_CACHE_ENV, "").strip()
    return Path(text).expanduser().resolve() if text else None


class DataCatalogDuckDB:
    """DuckDB-backed data catalog."""

    def __init__(
        self,
        db_path: Path | UPath | str | None = None,
        *,
        read_only: bool = False,
        layered: bool = True,
    ):
        """Open the cache at *db_path*, in memory when it is ``None``.

        ``read_only`` opens the file for reading only and never creates nor
        migrates it. ``layered=False`` opens the file itself even inside a
        launched case: the launcher merging a case passes it.
        """
        self._db_path: Path | None = None
        self._shared_path: Path | None = None
        self._read_only = read_only
        if db_path is None:
            self._conn = duckdb.connect(":memory:")
            backend_path: Path | None = None
        else:
            db_path = Path(str(db_path)).expanduser().resolve()
            self._db_path = db_path
            private = private_cache_path() if layered and not read_only else None
            if read_only:
                self._conn = connect_with_retry(str(db_path), read_only=True)
            elif private is not None and private != db_path:
                # The shared cache is read per query; this process writes its own.
                self._shared_path = db_path
                private.parent.mkdir(parents=True, exist_ok=True)
                self._conn = connect_with_retry(str(private), block_size=HMP_DUCKDB_BLOCK_SIZE)
            else:
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = connect_with_retry(str(db_path), block_size=HMP_DUCKDB_BLOCK_SIZE)
            backend_path = db_path

        if not read_only:
            ensure_schema_safe(self._conn)
        self._backend: CacheBackend = DuckDBCacheBackend.from_connection(
            self._conn, path=backend_path
        )

    @property
    def db_path(self) -> Path | None:
        """File of the cache, or ``None`` for an in-memory cache."""
        return self._db_path

    @property
    def read_only(self) -> bool:
        """Whether this catalog was opened for reading only."""
        return self._read_only

    @property
    def layered(self) -> bool:
        """Whether writes go to a private cache and reads also ask the shared one."""
        return self._shared_path is not None

    @contextmanager
    def _shared(self) -> Iterator[DataCatalogDuckDB | None]:
        """Open the shared cache read-only for one query, or yield ``None``."""
        if self._shared_path is None or not self._shared_path.is_file():
            yield None
            return
        shared = DataCatalogDuckDB(self._shared_path, read_only=True)
        try:
            yield shared
        finally:
            shared.close()

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

    def resolve_path(self, file_path: Path | str, *, variable: str | None = None) -> Path:
        """Return the file a stored ``file_path`` names, whatever the cwd."""
        return cache_store.resolve_entry_path(self, file_path, variable=variable)

    @staticmethod
    def _frozen_enabled() -> bool:
        return cache_store.frozen_enabled()

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

    def _reject_frozen_entry_mismatch(self, entry: CatalogEntry) -> None:
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
        write_sidecar: bool = True,
    ) -> int:
        """Register or update a data file entry. Returns entry id (-1 on error).

        ``write_sidecar=False`` leaves the sidecar of the file as it is: an
        imported file keeps the one that came with it.
        """
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
            write_sidecar=write_sidecar,
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
        product_version: str | None = None,
    ) -> CatalogEntry | None:
        """Find a cached entry covering the requested extent/period (superset).

        With a *product_version*, an entry fetched from another version of the
        provider's product, or from one that recorded none, does not answer.

        A layered catalog asks the shared cache first, then its private one.
        """
        query = {
            "variable": variable,
            "source": source,
            "station_id": station_id,
            "bbox": bbox,
            "date_start": date_start,
            "date_end": date_end,
            "product_version": product_version,
        }
        with self._shared() as shared:
            if shared is not None:
                found = cache_queries.find_cached(shared, **query)
                if found is not None:
                    return found
        return cache_queries.find_cached(self, **query)

    def entry_for_file(self, file_path: Path | str) -> CatalogEntry | None:
        """Return the newest entry that serves one file, shared cache first, or None."""
        with self._shared() as shared:
            if shared is not None:
                found = cache_queries.entry_for_file(shared, file_path)
                if found is not None:
                    return found
        return cache_queries.entry_for_file(self, file_path)

    def custom_file_mtime(self, *, variable: str, file_path: Path | str) -> float | None:
        """Return the ``file_mtime`` indexed for one custom file, or None."""
        mtime = cache_queries.custom_file_mtime(self, variable=variable, file_path=file_path)
        if mtime is not None:
            return mtime
        with self._shared() as shared:
            if shared is None:
                return None
            return cache_queries.custom_file_mtime(shared, variable=variable, file_path=file_path)

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> pd.DataFrame:
        """List catalog entries as a DataFrame; a layered catalog lists both caches."""
        if self._shared_path is None:
            return cache_queries.list_entries(
                self,
                variable=variable,
                source=source,
                limit=limit,
                offset=offset,
            )
        frames = [cache_queries.list_entries(self, variable=variable, source=source)]
        with self._shared() as shared:
            if shared is not None:
                frames.insert(
                    0, cache_queries.list_entries(shared, variable=variable, source=source)
                )
        merged = pd.concat([frame for frame in frames if not frame.empty] or frames[:1])
        merged = merged.reset_index(drop=True)
        end = None if limit is None else offset + limit
        return merged.iloc[offset:end].reset_index(drop=True)

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
        dry_run: bool = False,
    ) -> int:
        """Remove matching entries. Returns count deleted, or the count found under *dry_run*."""
        return cache_lifecycle.invalidate(
            self,
            variable=variable,
            source=source,
            station_id=station_id,
            delete_files=delete_files,
            dry_run=dry_run,
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
        dry_run: bool = False,
    ) -> int:
        """Delete cache entries older than *days* days. Returns count removed, or found under *dry_run*."""
        return cache_lifecycle.prune_older_than(
            self,
            days=days,
            delete_files=delete_files,
            dry_run=dry_run,
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


_STATION_COLUMNS = ("station_id", "variable", "source", "lat", "lon", "z", "name")
_STATION_VALIDITY = ("first_valid", "last_valid")


def merge_private_cache(shared_path: Path | str, private_path: Path | str) -> int:
    """Merge the entries and stations of a private cache into the shared one.

    Returns the number of entries merged. Each entry goes through
    :meth:`DataCatalogDuckDB.register`, so an entry the shared cache already
    holds is updated in place. The private file is left as it is; the caller
    removes it once the merge returned.
    """
    private = Path(private_path)
    if not private.is_file():
        return 0
    with DataCatalogDuckDB(private, read_only=True) as source:
        entries = source.backend.query("SELECT * FROM entries ORDER BY id")
        stations = source.backend.query("SELECT * FROM stations")
    if entries.empty and stations.empty:
        return 0
    with DataCatalogDuckDB(shared_path, layered=False) as shared:
        for row in entries.to_dict(orient="records"):
            shared.register(
                variable=row["variable"],
                source=row["source"],
                file_path=row["file_path"],
                station_id=_cell(row.get("station_id")),
                bbox=_bbox_of(row),
                crs=_cell(row.get("crs")),
                date_start=_cell(row.get("date_start")),
                date_end=_cell(row.get("date_end")),
                frequency=_cell(row.get("frequency")),
                unit=_cell(row.get("unit")),
                source_unit=_cell(row.get("source_unit")),
                is_custom=bool(row.get("is_custom")),
                file_mtime=_cell(row.get("file_mtime")),
                file_sha256=_cell(row.get("sha256")),
                fetch_metadata=_metadata_of(row.get("fetch_metadata")),
            )
        for row in stations.to_dict(orient="records"):
            shared.upsert_station(
                **{key: _cell(row.get(key)) for key in (*_STATION_COLUMNS, *_STATION_VALIDITY)}
            )
    return len(entries)


def _cell(value: object) -> object:
    """Return ``None`` for a missing cell of a DataFrame row, the value otherwise."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value


def _bbox_of(row: dict) -> tuple | None:
    box = tuple(_cell(row.get(key)) for key in ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax"))
    return None if all(value is None for value in box) else box


def _metadata_of(value: object) -> dict | None:
    value = _cell(value)
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return json.loads(str(value))
