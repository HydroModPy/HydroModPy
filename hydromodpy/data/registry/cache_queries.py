"""Cache queries: read-only lookups over catalog entries.

Concern: never mutates the catalog. Returns rows, dataframes, or
small typed views (``CatalogEntry``). Frozen-mode rejection on a
cache miss is delegated to :mod:`cache_store`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.data.registry.cache_store import (
    dt_to_str,
    reject_frozen_cache_miss,
    reject_frozen_entry_mismatch,
)

if TYPE_CHECKING:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

logger = get_logger(__name__)


class CatalogEntry:
    """Lightweight object mimicking the SQLAlchemy CatalogEntry for callers
    that access attributes by name (e.g. ``entry.station_id``)."""

    __slots__ = (
        "id",
        "variable",
        "source",
        "station_id",
        "bbox_xmin",
        "bbox_ymin",
        "bbox_xmax",
        "bbox_ymax",
        "crs",
        "date_start",
        "date_end",
        "frequency",
        "unit",
        "source_unit",
        "file_path",
        "file_mtime",
        "sha256",
        "created_at",
        "is_custom",
        "fetch_metadata",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def find_cached(
    catalog: DataCatalogDuckDB,
    *,
    variable: str,
    source: str,
    station_id: str | None = None,
    bbox: tuple | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
) -> CatalogEntry | None:
    """Find a cached entry covering the requested extent/period (superset)."""
    if bbox is not None and not (bbox[0] <= bbox[2] and bbox[1] <= bbox[3]):
        logger.warning("find_cached() called with inverted bbox: %s", bbox)
        return None

    query = "SELECT * FROM entries WHERE variable = ? AND source = ?"
    params: list = [variable, source]

    if station_id is not None:
        query += " AND station_id = ?"
        params.append(station_id)
    if bbox is not None:
        query += " AND bbox_xmin <= ? AND bbox_ymin <= ? AND bbox_xmax >= ? AND bbox_ymax >= ?"
        params.extend([bbox[0], bbox[1], bbox[2], bbox[3]])
    if date_start is not None:
        query += " AND date_start <= ?"
        params.append(dt_to_str(date_start))
    if date_end is not None:
        query += " AND date_end >= ?"
        params.append(dt_to_str(date_end))

    query += " ORDER BY id DESC LIMIT 1"
    backend = catalog.backend
    row = backend.fetch_one(query, params)
    if row is None:
        reject_frozen_cache_miss(
            catalog,
            variable=variable,
            source=source,
            station_id=station_id,
        )
        return None

    desc = backend.description() or []
    cols = [d[0] for d in desc]
    entry = CatalogEntry(**dict(zip(cols, row, strict=False)))
    reject_frozen_entry_mismatch(catalog, entry)
    return entry


def list_entries(
    catalog: DataCatalogDuckDB,
    *,
    variable: str | None = None,
    source: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> pd.DataFrame:
    """List catalog entries as a DataFrame."""
    query = (
        "SELECT id, variable, source, station_id, date_start, date_end, "
        "file_path, file_mtime, sha256, source_unit, is_custom, fetch_metadata FROM entries"
    )
    params: list = []
    clauses = []
    if variable:
        clauses.append("variable = ?")
        params.append(variable)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += f" OFFSET {offset}"
    if limit is not None:
        query += f" LIMIT {limit}"

    df = catalog.backend.query(query, params)
    if "is_custom" in df.columns:
        df["is_custom"] = df["is_custom"].astype(bool)
    for column in ("date_start", "date_end"):
        if column in df.columns:
            df[column] = df[column].map(_format_catalog_timestamp)
    return df


def table_names(catalog: DataCatalogDuckDB) -> list[str]:
    """Return the list of tables present in the catalog."""
    rows = catalog.backend.fetch_all(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    )
    return [r[0] for r in rows]


def _format_catalog_timestamp(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    return ts.isoformat(timespec="seconds")
