"""Data catalog backed by SQLAlchemy (SQLite by default, swappable to PostgreSQL).

Tracks metadata about downloaded/referenced data files. Does NOT store the data
itself, only what exists, where, and for which extent/period.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    Column, DateTime, Float, Index, Integer, String, Text,
    create_engine, text,
    inspect,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)
from hydromodpy.core.tools.log_manager import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 2


class _Base(DeclarativeBase):
    pass


class CatalogEntry(_Base):
    """One row = one data file."""

    __tablename__ = "entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    variable = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    station_id = Column(String, nullable=True)
    bbox_xmin = Column(Float, nullable=True)
    bbox_ymin = Column(Float, nullable=True)
    bbox_xmax = Column(Float, nullable=True)
    bbox_ymax = Column(Float, nullable=True)
    crs = Column(String, nullable=True)
    date_start = Column(String, nullable=True)
    date_end = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    source_unit = Column(String, nullable=True)
    file_path = Column(Text, nullable=False)
    file_mtime = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(tz=None))
    is_custom = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_entries_var_src_station", "variable", "source", "station_id"),
        Index("ix_entries_bbox", "bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax"),
    )


class ApiCoverage(_Base):
    """Static metadata: which APIs cover which areas."""

    __tablename__ = "api_coverage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    variable = Column(String, nullable=False)
    source = Column(String, nullable=False)
    country = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    bbox_xmin = Column(Float, nullable=True)
    bbox_ymin = Column(Float, nullable=True)
    bbox_xmax = Column(Float, nullable=True)
    bbox_ymax = Column(Float, nullable=True)


class DataCatalog:
    """Lightweight catalog over SQLAlchemy (SQLite default, PostgreSQL ready).

    Pass None for in-memory DB, a Path for SQLite, or a URL string for PostgreSQL.

    Thread safety: this class is designed for single-threaded access.
    Concurrent access from multiple threads or processes may cause race conditions.
    """

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            url = "sqlite:///:memory:"
        elif str(db_path).startswith(("postgresql://", "sqlite://")):
            url = str(db_path)
        else:
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{db_path}"

        if url.startswith("sqlite://"):
            self.engine = create_engine(url, echo=False, connect_args={"timeout": 30})
        else:
            self.engine = create_engine(url, echo=False)

        _Base.metadata.create_all(self.engine)
        self._SessionFactory = sessionmaker(bind=self.engine)
        self._apply_migrations()

    def _apply_migrations(self):
        """Apply lightweight additive schema upgrades with version tracking."""
        # Ensure _schema_meta table exists
        with self.engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS _schema_meta "
                "(version INTEGER NOT NULL)"
            ))
            conn.commit()

        # Read current version
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT version FROM _schema_meta")).fetchone()
            if row is None:
                current_version = 0
                conn.execute(text("INSERT INTO _schema_meta (version) VALUES (0)"))
                conn.commit()
            else:
                current_version = row[0]

        # v1: composite index on (variable, source, station_id)
        if current_version < 1:
            try:
                with self.engine.connect() as conn:
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_entries_var_src_station "
                        "ON entries (variable, source, station_id)"
                    ))
                    conn.commit()
                self._set_schema_version(1)
            except Exception as exc:
                logger.warning("Migration v1 (composite index) failed: %s", exc)

        # v2: add source_unit column
        if current_version < 2:
            try:
                inspector = inspect(self.engine)
                columns = {col["name"] for col in inspector.get_columns("entries")}
                if "source_unit" not in columns:
                    with self.engine.begin() as conn:
                        conn.execute(text(
                            "ALTER TABLE entries ADD COLUMN source_unit TEXT"
                        ))
                self._set_schema_version(2)
            except Exception as exc:
                logger.warning("Migration v2 (source_unit column) failed: %s", exc)

    def _set_schema_version(self, version: int) -> None:
        """Update the schema version in _schema_meta."""
        with self.engine.connect() as conn:
            conn.execute(
                text("UPDATE _schema_meta SET version = :v"), {"v": version}
            )
            conn.commit()

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
    ) -> int:
        """Register a data file (upsert). Returns entry id.

        If an entry with the same (variable, source, station_id) already exists,
        it is updated. Otherwise a new entry is created.

        file_path can be relative (just the filename) for portability.
        If file_mtime is not provided, it is read from the file if it exists.
        Returns -1 on integrity error.
        """
        file_path = Path(file_path)
        if file_mtime is None:
            try:
                mtime = file_path.stat().st_mtime if file_path.exists() else None
            except OSError:
                mtime = None
        else:
            mtime = file_mtime

        try:
            with self._SessionFactory() as session:
                # Look for existing entry with same key
                q = session.query(CatalogEntry).filter(
                    CatalogEntry.variable == variable,
                    CatalogEntry.source == source,
                )
                if station_id is not None:
                    q = q.filter(CatalogEntry.station_id == station_id)
                else:
                    q = q.filter(CatalogEntry.station_id.is_(None))
                    # For grid data (no station_id), also match on file_path
                    # so that two different files don't overwrite each other.
                    q = q.filter(CatalogEntry.file_path == str(file_path))

                entry = q.first()

                if entry is not None:
                    # Update existing
                    entry.bbox_xmin = bbox[0] if bbox else None
                    entry.bbox_ymin = bbox[1] if bbox else None
                    entry.bbox_xmax = bbox[2] if bbox else None
                    entry.bbox_ymax = bbox[3] if bbox else None
                    entry.crs = crs
                    entry.date_start = _dt_to_str(date_start)
                    entry.date_end = _dt_to_str(date_end)
                    entry.frequency = frequency
                    entry.unit = unit
                    entry.source_unit = source_unit
                    entry.file_path = str(file_path)
                    entry.file_mtime = mtime
                    entry.is_custom = 1 if is_custom else 0
                else:
                    # Insert new
                    entry = CatalogEntry(
                        variable=variable,
                        source=source,
                        station_id=station_id,
                        bbox_xmin=bbox[0] if bbox else None,
                        bbox_ymin=bbox[1] if bbox else None,
                        bbox_xmax=bbox[2] if bbox else None,
                        bbox_ymax=bbox[3] if bbox else None,
                        crs=crs,
                        date_start=_dt_to_str(date_start),
                        date_end=_dt_to_str(date_end),
                        frequency=frequency,
                        unit=unit,
                        source_unit=source_unit,
                        file_path=str(file_path),
                        file_mtime=mtime,
                        is_custom=1 if is_custom else 0,
                    )
                    session.add(entry)

                session.commit()
                session.refresh(entry)
                return entry.id
        except IntegrityError as exc:
            logger.warning("IntegrityError in register(): %s", exc)
            return -1

    def find_cached(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None = None,
        bbox: tuple | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
    ) -> CatalogEntry | None:
        """Find cached entry covering the requested extent/period (superset logic)."""
        # Validate bbox orientation
        if bbox is not None:
            if not (bbox[0] <= bbox[2] and bbox[1] <= bbox[3]):
                logger.warning(
                    "find_cached() called with inverted bbox: %s", bbox,
                )
                return None

        with self._SessionFactory() as session:
            q = session.query(CatalogEntry).filter(
                CatalogEntry.variable == variable,
                CatalogEntry.source == source,
            )
            if station_id is not None:
                q = q.filter(CatalogEntry.station_id == station_id)
            if bbox is not None:
                q = q.filter(
                    CatalogEntry.bbox_xmin <= bbox[0],
                    CatalogEntry.bbox_ymin <= bbox[1],
                    CatalogEntry.bbox_xmax >= bbox[2],
                    CatalogEntry.bbox_ymax >= bbox[3],
                )
            if date_start is not None:
                q = q.filter(CatalogEntry.date_start <= _dt_to_str(date_start))
            if date_end is not None:
                q = q.filter(CatalogEntry.date_end >= _dt_to_str(date_end))

            entry = q.order_by(CatalogEntry.id.desc()).first()
            if entry is not None:
                session.expunge(entry)
            return entry

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> pd.DataFrame:
        """List catalog entries as DataFrame."""
        with self._SessionFactory() as session:
            q = session.query(CatalogEntry)
            if variable:
                q = q.filter(CatalogEntry.variable == variable)
            if source:
                q = q.filter(CatalogEntry.source == source)
            if offset:
                q = q.offset(offset)
            if limit is not None:
                q = q.limit(limit)
            rows = [
                {
                    "id": e.id, "variable": e.variable, "source": e.source,
                    "station_id": e.station_id, "date_start": e.date_start,
                    "date_end": e.date_end, "file_path": e.file_path,
                    "source_unit": e.source_unit,
                    "is_custom": bool(e.is_custom),
                }
                for e in q.all()
            ]
        return pd.DataFrame(rows)

    def invalidate(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        station_id: str | None = None,
        delete_files: bool = False,
    ) -> int:
        """Remove matching entries. Returns count of deleted entries."""
        try:
            with self._SessionFactory() as session:
                q = session.query(CatalogEntry)
                if variable:
                    q = q.filter(CatalogEntry.variable == variable)
                if source:
                    q = q.filter(CatalogEntry.source == source)
                if station_id:
                    q = q.filter(CatalogEntry.station_id == station_id)

                entries = q.all()
                count = len(entries)
                for entry in entries:
                    if delete_files:
                        p = Path(entry.file_path)
                        try:
                            if p.exists():
                                p.unlink()
                        except OSError as exc:
                            logger.warning(
                                "Failed to delete file %s: %s", p, exc,
                            )
                    session.delete(entry)
                session.commit()
            return count
        except Exception as exc:
            logger.warning("invalidate() failed: %s", exc)
            return 0


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
        """Delete grid entries fully contained within the given bbox+dates.

        Used after registering a new (larger) grid to remove smaller grids
        that are now redundant.  Deletes both catalog entries and files on disk.
        Returns the number of removed entries.
        """
        try:
            with self._SessionFactory() as session:
                q = session.query(CatalogEntry).filter(
                    CatalogEntry.variable == variable,
                    CatalogEntry.source == source,
                    CatalogEntry.station_id.is_(None),  # grid data only
                    CatalogEntry.is_custom == 0,  # never subsume user data
                )
                if exclude_id is not None:
                    q = q.filter(CatalogEntry.id != exclude_id)
                # Spatial subset: existing bbox fully inside new bbox
                if bbox is not None:
                    q = q.filter(
                        CatalogEntry.bbox_xmin >= bbox[0],
                        CatalogEntry.bbox_ymin >= bbox[1],
                        CatalogEntry.bbox_xmax <= bbox[2],
                        CatalogEntry.bbox_ymax <= bbox[3],
                    )
                # Temporal subset: existing dates fully inside new dates
                if date_start is not None:
                    q = q.filter(CatalogEntry.date_start >= date_start)
                if date_end is not None:
                    q = q.filter(CatalogEntry.date_end <= date_end)

                entries = q.all()
                count = 0
                for entry in entries:
                    p = Path(entry.file_path)
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError as exc:
                        logger.warning(
                            "Failed to delete file %s: %s", p, exc,
                        )
                    session.delete(entry)
                    count += 1
                session.commit()
            return count
        except Exception as exc:
            logger.warning("subsume_entries() failed: %s", exc)
            return 0

    def cleanup(self) -> int:
        """Remove catalog entries whose files no longer exist on disk.

        Sentinel entries (SENTINEL_CUSTOM / SENTINEL_EMPTY) are skipped.
        Returns the number of removed entries.
        """
        ids_to_delete: list[int] = []
        with self._SessionFactory() as session:
            entries = session.query(CatalogEntry).all()
            for entry in entries:
                if entry.file_path in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
                    continue
                try:
                    exists = Path(entry.file_path).exists()
                except OSError as exc:
                    logger.warning(
                        "Error checking file %s: %s", entry.file_path, exc,
                    )
                    ids_to_delete.append(entry.id)
                    continue
                if not exists:
                    ids_to_delete.append(entry.id)

            if ids_to_delete:
                session.query(CatalogEntry).filter(
                    CatalogEntry.id.in_(ids_to_delete),
                ).delete(synchronize_session="fetch")
                session.commit()
        return len(ids_to_delete)


def _dt_to_str(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)
