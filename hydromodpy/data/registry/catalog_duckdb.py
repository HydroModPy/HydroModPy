"""Data catalog backed by DuckDB (drop-in replacement for the SQLAlchemy catalog).

Same public API as DataCatalog so that DataStore and all variable managers
work without changes.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY

logger = logging.getLogger(__name__)

_RETRY = 3
_BACKOFF = 0.1

_ENTRIES_DDL = """
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY DEFAULT nextval('entries_seq'),
    variable      VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    station_id    VARCHAR,
    bbox_xmin     DOUBLE,
    bbox_ymin     DOUBLE,
    bbox_xmax     DOUBLE,
    bbox_ymax     DOUBLE,
    crs           VARCHAR,
    date_start    VARCHAR,
    date_end      VARCHAR,
    frequency     VARCHAR,
    unit          VARCHAR,
    source_unit   VARCHAR,
    file_path     TEXT NOT NULL,
    file_mtime    DOUBLE,
    created_at    TIMESTAMP DEFAULT now(),
    is_custom     INTEGER DEFAULT 0,
    fetch_metadata JSON
);

CREATE INDEX IF NOT EXISTS ix_entries_var_src_station
    ON entries (variable, source, station_id);
CREATE INDEX IF NOT EXISTS ix_entries_bbox
    ON entries (bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax);
"""

_API_COVERAGE_DDL = """
CREATE TABLE IF NOT EXISTS api_coverage (
    id          INTEGER PRIMARY KEY DEFAULT nextval('api_coverage_seq'),
    variable    VARCHAR NOT NULL,
    source      VARCHAR NOT NULL,
    country     VARCHAR,
    description VARCHAR,
    bbox_xmin   DOUBLE,
    bbox_ymin   DOUBLE,
    bbox_xmax   DOUBLE,
    bbox_ymax   DOUBLE
);
"""


class _CatalogEntry:
    """Lightweight object mimicking the SQLAlchemy CatalogEntry for callers
    that access attributes by name (e.g. ``entry.station_id``)."""

    __slots__ = (
        "id", "variable", "source", "station_id",
        "bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax",
        "crs", "date_start", "date_end", "frequency",
        "unit", "source_unit", "file_path", "file_mtime",
        "created_at", "is_custom", "fetch_metadata",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class DataCatalogDuckDB:
    """DuckDB-backed data catalog with the same API as DataCatalog."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            self._conn = duckdb.connect(":memory:")
        else:
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_path))

        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS entries_seq START 1")
        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS api_coverage_seq START 1")
        self._conn.execute(_ENTRIES_DDL)
        self._conn.execute(_API_COVERAGE_DDL)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DataCatalogDuckDB:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

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
        fetch_metadata: dict | None = None,
    ) -> int:
        """Register or update a data file entry. Returns entry id (-1 on error)."""
        file_path = Path(file_path)
        if file_mtime is None:
            try:
                mtime = file_path.stat().st_mtime if file_path.exists() else None
            except OSError:
                mtime = None
        else:
            mtime = file_mtime

        ds = _dt_to_str(date_start)
        de = _dt_to_str(date_end)
        bx = bbox or (None, None, None, None)

        # Look for existing entry
        if station_id is not None:
            existing = self._conn.execute(
                "SELECT id FROM entries WHERE variable = ? AND source = ? AND station_id = ?",
                [variable, source, station_id],
            ).fetchone()
        else:
            existing = self._conn.execute(
                "SELECT id FROM entries WHERE variable = ? AND source = ? "
                "AND station_id IS NULL AND file_path = ?",
                [variable, source, str(file_path)],
            ).fetchone()

        for attempt in range(_RETRY):
            try:
                if existing is not None:
                    eid = existing[0]
                    self._conn.execute(
                        """UPDATE entries SET
                           bbox_xmin=?, bbox_ymin=?, bbox_xmax=?, bbox_ymax=?,
                           crs=?, date_start=?, date_end=?, frequency=?,
                           unit=?, source_unit=?, file_path=?, file_mtime=?,
                           is_custom=?, fetch_metadata=?
                           WHERE id=?""",
                        [
                            bx[0], bx[1], bx[2], bx[3],
                            crs, ds, de, frequency,
                            unit, source_unit, str(file_path), mtime,
                            1 if is_custom else 0,
                            _json_or_none(fetch_metadata),
                            eid,
                        ],
                    )
                    return eid
                else:
                    self._conn.execute(
                        """INSERT INTO entries
                           (variable, source, station_id,
                            bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                            crs, date_start, date_end, frequency,
                            unit, source_unit, file_path, file_mtime,
                            is_custom, fetch_metadata)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [
                            variable, source, station_id,
                            bx[0], bx[1], bx[2], bx[3],
                            crs, ds, de, frequency,
                            unit, source_unit, str(file_path), mtime,
                            1 if is_custom else 0,
                            _json_or_none(fetch_metadata),
                        ],
                    )
                    row = self._conn.execute(
                        "SELECT currval('entries_seq')"
                    ).fetchone()
                    return row[0]
            except duckdb.IOException:
                if attempt < _RETRY - 1:
                    time.sleep(_BACKOFF * (2 ** attempt))
                else:
                    raise
            except Exception as exc:
                logger.warning("register() failed: %s", exc)
                return -1
        return -1

    # -- find_cached -----------------------------------------------------------

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
            params.append(_dt_to_str(date_start))
        if date_end is not None:
            query += " AND date_end >= ?"
            params.append(_dt_to_str(date_end))

        query += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(query, params).fetchone()
        if row is None:
            return None

        cols = [d[0] for d in self._conn.description]
        return _CatalogEntry(**dict(zip(cols, row)))

    # -- list_entries ----------------------------------------------------------

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> pd.DataFrame:
        """List catalog entries as a DataFrame."""
        query = "SELECT id, variable, source, station_id, date_start, date_end, file_path, source_unit, is_custom, fetch_metadata FROM entries"
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

        df = self._conn.execute(query, params).fetchdf()
        if "is_custom" in df.columns:
            df["is_custom"] = df["is_custom"].astype(bool)
        return df

    # -- invalidate ------------------------------------------------------------

    def invalidate(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        station_id: str | None = None,
        delete_files: bool = False,
    ) -> int:
        """Remove matching entries. Returns count deleted.

        Sentinel entries (SENTINEL_CUSTOM, SENTINEL_EMPTY file_path) are
        excluded from deletion to preserve placeholder records.
        """
        try:
            clauses, params = _build_filter(variable, source, station_id)
            # Protect sentinel entries
            clauses.append("file_path NOT IN (?, ?)")
            params.extend([SENTINEL_CUSTOM, SENTINEL_EMPTY])
            where = " WHERE " + " AND ".join(clauses)

            if delete_files:
                rows = self._conn.execute(
                    f"SELECT file_path FROM entries{where}", params,
                ).fetchall()
                for (fp,) in rows:
                    _try_unlink(fp)

            result = self._conn.execute(
                f"DELETE FROM entries{where} RETURNING id", params,
            ).fetchall()
            return len(result)
        except Exception as exc:
            logger.warning("invalidate() failed: %s", exc)
            return 0

    # -- subsume_entries -------------------------------------------------------

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
        try:
            query = (
                "SELECT id, file_path FROM entries "
                "WHERE variable = ? AND source = ? "
                "AND station_id IS NULL AND is_custom = 0"
            )
            params: list = [variable, source]

            if exclude_id is not None:
                query += " AND id != ?"
                params.append(exclude_id)
            if bbox is not None:
                query += " AND bbox_xmin >= ? AND bbox_ymin >= ? AND bbox_xmax <= ? AND bbox_ymax <= ?"
                params.extend([bbox[0], bbox[1], bbox[2], bbox[3]])
            if date_start is not None:
                query += " AND date_start >= ?"
                params.append(date_start)
            if date_end is not None:
                query += " AND date_end <= ?"
                params.append(date_end)

            rows = self._conn.execute(query, params).fetchall()
            count = 0
            for eid, fp in rows:
                _try_unlink(fp)
                self._conn.execute("DELETE FROM entries WHERE id = ?", [eid])
                count += 1
            return count
        except Exception as exc:
            logger.warning("subsume_entries() failed: %s", exc)
            return 0

    # -- cleanup ---------------------------------------------------------------

    def cleanup(self) -> int:
        """Remove entries whose files no longer exist on disk."""
        rows = self._conn.execute("SELECT id, file_path FROM entries").fetchall()
        ids_to_delete = []
        for eid, fp in rows:
            if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
                continue
            try:
                if not Path(fp).exists():
                    ids_to_delete.append(eid)
            except OSError:
                ids_to_delete.append(eid)

        if ids_to_delete:
            placeholders = ",".join("?" * len(ids_to_delete))
            self._conn.execute(
                f"DELETE FROM entries WHERE id IN ({placeholders})",
                ids_to_delete,
            )
        return len(ids_to_delete)


def _dt_to_str(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _json_or_none(d: dict | None) -> str | None:
    if d is None:
        return None
    import json
    return json.dumps(d)


def _build_filter(variable, source, station_id):
    clauses, params = [], []
    if variable:
        clauses.append("variable = ?")
        params.append(variable)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if station_id:
        clauses.append("station_id = ?")
        params.append(station_id)
    return clauses, params


def _try_unlink(fp: str) -> None:
    if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
        return
    try:
        p = Path(fp)
        if p.exists():
            p.unlink()
    except OSError as exc:
        logger.warning("Failed to delete file %s: %s", fp, exc)
