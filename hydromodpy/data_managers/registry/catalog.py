"""Data catalog backed by SQLAlchemy (SQLite by default, swappable to PostgreSQL).

Tracks metadata about downloaded/referenced data files. Does NOT store the data
itself, only what exists, where, and for which extent/period.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text,
    create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

SCHEMA_VERSION = 1


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
    file_path = Column(Text, nullable=False)
    file_mtime = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(tz=None))
    is_custom = Column(Integer, default=0)


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

        self.engine = create_engine(url, echo=False)
        _Base.metadata.create_all(self.engine)
        self._SessionFactory = sessionmaker(bind=self.engine)
        self._apply_migrations()

    def _apply_migrations(self):
        """Placeholder for future schema upgrades."""
        pass

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
        is_custom: bool = False,
    ) -> int:
        """Register a data file. Returns entry id."""
        file_path = Path(file_path)
        mtime = file_path.stat().st_mtime if file_path.exists() else None
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
            file_path=str(file_path),
            file_mtime=mtime,
            is_custom=1 if is_custom else 0,
        )
        with self._SessionFactory() as session:
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry.id

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

            entry = q.first()
            if entry is not None:
                session.expunge(entry)
            return entry

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
    ) -> pd.DataFrame:
        """List catalog entries as DataFrame."""
        with self._SessionFactory() as session:
            q = session.query(CatalogEntry)
            if variable:
                q = q.filter(CatalogEntry.variable == variable)
            if source:
                q = q.filter(CatalogEntry.source == source)
            rows = [
                {
                    "id": e.id, "variable": e.variable, "source": e.source,
                    "station_id": e.station_id, "date_start": e.date_start,
                    "date_end": e.date_end, "file_path": e.file_path,
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
                    if p.exists():
                        p.unlink()
                session.delete(entry)
            session.commit()
        return count


def _dt_to_str(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)
