"""Unit tests for the pre-migration backup policy of ``ensure_schema_safe``."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.logging import get_logger
from hydromodpy.core.migrations import ensure_schema_safe, list_backups
from hydromodpy.core.migrations.auto_boot import NO_BACKUP_COMPONENTS

_CACHE_COMPONENT = "data_cache"


@pytest.fixture
def versions_dir(tmp_path: Path) -> Path:
    """Migration directory holding one trivial version."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_initial.sql").write_text(
        "CREATE TABLE IF NOT EXISTS entries (id INTEGER);",
        encoding="utf-8",
    )
    return directory


def _backup_table_count(backup: Path) -> int:
    conn = duckdb.connect(str(backup), read_only=True)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row is not None else 0


def test_fresh_database_writes_no_empty_backup(tmp_path: Path, versions_dir: Path) -> None:
    """A database with no table yet is never snapshotted (the copy holds nothing)."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = get_logger("hydromodpy.core.migrations.auto_boot")
    logger.addHandler(handler)

    db_path = tmp_path / "cache.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=versions_dir,
            component=_CACHE_COMPONENT,
        )
    finally:
        conn.close()
        logger.removeHandler(handler)

    assert list_backups(db_path) == []
    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("no table yet" in message for message in warnings)


def test_populated_database_keeps_its_backup(tmp_path: Path, versions_dir: Path) -> None:
    """A non-reconstructible component still gets a snapshot holding its tables."""
    db_path = tmp_path / "cache.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE payload (id INTEGER)")
        conn.execute("INSERT INTO payload VALUES (1)")
        conn.execute("CHECKPOINT")
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=versions_dir,
            component=_CACHE_COMPONENT,
        )
    finally:
        conn.close()

    backups = list_backups(db_path)
    assert len(backups) == 1
    assert _backup_table_count(backups[0]) > 0


def test_catalog_component_skips_backup(tmp_path: Path, versions_dir: Path) -> None:
    """The project catalog is a reconstructible index: no snapshot, even populated."""
    assert "catalog" in NO_BACKUP_COMPONENTS
    db_path = tmp_path / "catalog.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE payload (id INTEGER)")
        conn.execute("CHECKPOINT")
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=versions_dir,
            component="catalog",
        )
    finally:
        conn.close()

    assert list_backups(db_path) == []
