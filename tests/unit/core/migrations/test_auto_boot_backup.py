"""Unit tests for the pre-migration backup policy of ``ensure_schema_safe``."""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.exceptions import BackupFailedError
from hydromodpy.core.io.filesystem import native_io_path
from hydromodpy.core.logging import get_logger
from hydromodpy.core.migrations import auto_boot, ensure_schema_safe, list_backups
from hydromodpy.core.migrations.auto_boot import MAX_BACKUPS, NO_BACKUP_COMPONENTS, backup_path_for
from hydromodpy.core.migrations.runner import current_version
from hydromodpy.core.state.paths import CATALOG_FILENAME

_CACHE_COMPONENT = "data_cache"
_MAX_PATH = 259
_STAMP = "20260101T000000Z"


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


@pytest.mark.parametrize(
    ("component", "filename"),
    [("catalog", CATALOG_FILENAME), ("index", "index.duckdb")],
)
def test_an_index_component_skips_backup(
    tmp_path: Path, versions_dir: Path, component: str, filename: str
) -> None:
    """An index is rebuilt, never restored: no snapshot, even populated."""
    assert component in NO_BACKUP_COMPONENTS
    db_path = tmp_path / filename
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE payload (id INTEGER)")
        conn.execute("CHECKPOINT")
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=versions_dir,
            component=component,
        )
    finally:
        conn.close()

    assert list_backups(db_path) == []


def test_only_the_source_data_cache_is_backed_up() -> None:
    """The cache is the one database a rebuild cannot reproduce."""
    assert NO_BACKUP_COMPONENTS == frozenset({"catalog", "index"})
    assert _CACHE_COMPONENT not in NO_BACKUP_COMPONENTS


def _refuse_to_copy(*args: object, **kwargs: object) -> None:
    raise PermissionError("locked")


def _write_nothing(*args: object) -> None:
    return None


@pytest.fixture
def deep_dir(tmp_path: Path) -> Iterator[Path]:
    """Directory nested deep enough that its backup path overflows MAX_PATH."""
    top = tmp_path / "nested_project_level"
    deep = tmp_path
    while len(str(backup_path_for(deep / "cache.duckdb", timestamp=_STAMP))) <= _MAX_PATH:
        deep = deep / "nested_project_level"
    os.makedirs(native_io_path(deep), exist_ok=True)
    try:
        yield deep
    finally:
        shutil.rmtree(native_io_path(top), ignore_errors=True)


@pytest.mark.skipif(os.name != "nt", reason="MAX_PATH only caps Windows filesystems")
def test_backup_survives_a_path_longer_than_max_path(
    tmp_path: Path, deep_dir: Path, versions_dir: Path
) -> None:
    """A deeply nested project still gets a real, listable pre-migration snapshot."""
    db_path = deep_dir / "cache.duckdb"
    assert len(str(db_path)) < _MAX_PATH, "the database itself must stay addressable"
    assert len(str(backup_path_for(db_path, timestamp=_STAMP))) > _MAX_PATH

    stale = [
        backup_path_for(db_path, timestamp=f"20200101T{index:06d}Z")
        for index in range(MAX_BACKUPS + 2)
    ]
    os.makedirs(native_io_path(stale[0].parent), exist_ok=True)
    for old in stale:
        with open(native_io_path(old), "wb") as handle:
            handle.write(b"stale")

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
    assert len(backups) == MAX_BACKUPS, "the rolling prune must also see overlong paths"
    fresh = backups[-1]
    assert os.path.getsize(native_io_path(fresh)) > 0

    readable = tmp_path / "snapshot.duckdb"
    shutil.copy2(native_io_path(fresh), native_io_path(readable))
    assert _backup_table_count(readable) > 0


def test_an_unwritable_backup_aborts_the_migration(
    tmp_path: Path, versions_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot that never landed is never reported as taken: the migration aborts."""
    monkeypatch.setattr(auto_boot.shutil, "copy2", _refuse_to_copy)
    monkeypatch.setattr(auto_boot, "_copy_backup_from_connection", _write_nothing)

    db_path = tmp_path / "cache.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE payload (id INTEGER)")
        conn.execute("CHECKPOINT")
        with pytest.raises(BackupFailedError, match="could not be written"):
            ensure_schema_safe(
                conn,
                db_path=db_path,
                versions_dir=versions_dir,
                component=_CACHE_COMPONENT,
            )
        assert current_version(conn, component=_CACHE_COMPONENT) == 0
    finally:
        conn.close()

    assert list_backups(db_path) == []
