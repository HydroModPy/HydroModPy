"""Regression tests for ``ensure_schema_safe`` on a project catalog.

Three fixtures (empty / single sim / multi sim) are materialised at the
initial schema version and driven through the auto-boot path: the catalog
reaches the target version in place, the seeded simulations survive, and no
snapshot is written because a catalog is rebuilt (``hmp catalog reindex``),
never restored.

Also covers the opt-out (``HMP_AUTO_MIGRATE=0``) and the rolling backup cap.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.migrations import (
    AutoMigrationDisabled,
    ensure_schema_safe,
    list_backups,
)
from hydromodpy.core.migrations.auto_boot import NO_BACKUP_COMPONENTS
from hydromodpy.results.catalog.migrations import (
    CATALOG_COMPONENT,
    MIGRATIONS_DIR,
    current_version,
    target_version,
)

from .conftest import copy_fixture, discover_fixture_stems

ALL_FIXTURES = discover_fixture_stems()


def _count_simulations(db_path: Path) -> int:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0])
    finally:
        conn.close()


@pytest.mark.parametrize("stem", ALL_FIXTURES)
def test_catalog_migrates_in_place_without_a_backup(tmp_path: Path, stem: str) -> None:
    """A stale catalog reaches the target version, keeps its rows, gets no snapshot."""
    assert CATALOG_COMPONENT in NO_BACKUP_COMPONENTS
    db_path = copy_fixture(stem, tmp_path)
    pre_count = _count_simulations(db_path)
    assert list_backups(db_path) == []

    conn = duckdb.connect(str(db_path))
    try:
        assert current_version(conn) < target_version(), "fixture must have a pending migration"
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=MIGRATIONS_DIR,
            component=CATALOG_COMPONENT,
        )
        assert current_version(conn) == target_version()
        post_count = int(conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0])
        assert post_count == pre_count
    finally:
        conn.close()

    assert list_backups(db_path) == [], "a catalog is reindexed, not restored: never snapshotted"


@pytest.mark.parametrize("stem", ALL_FIXTURES[:1])
def test_opt_out_disables_migration(
    tmp_path: Path, stem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``HMP_AUTO_MIGRATE=0`` blocks the migration, and clearing it lets it through."""
    db_path = copy_fixture(stem, tmp_path)
    monkeypatch.setenv("HMP_AUTO_MIGRATE", "0")
    conn = duckdb.connect(str(db_path))
    try:
        stale_version = current_version(conn)
        assert stale_version < target_version(), "fixture must have a pending migration"
        with pytest.raises(AutoMigrationDisabled):
            ensure_schema_safe(
                conn,
                db_path=db_path,
                versions_dir=MIGRATIONS_DIR,
                component=CATALOG_COMPONENT,
            )
        assert current_version(conn) == stale_version
        assert list_backups(db_path) == []

        monkeypatch.delenv("HMP_AUTO_MIGRATE")
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=MIGRATIONS_DIR,
            component=CATALOG_COMPONENT,
        )
        assert current_version(conn) == target_version()
    finally:
        conn.close()


def test_rolling_backups_respect_max(tmp_path: Path) -> None:
    """Six successive prune cycles leave only ``MAX_BACKUPS`` snapshots behind."""
    from datetime import UTC, datetime, timedelta

    from hydromodpy.core.migrations.auto_boot import (
        MAX_BACKUPS,
        _prune_old_backups,
        backup_path_for,
    )

    db_path = tmp_path / "rolling.duckdb"
    db_path.write_bytes(b"\x00")
    for offset in range(MAX_BACKUPS + 3):
        stamp = (datetime.now(UTC) + timedelta(seconds=offset)).strftime("%Y%m%dT%H%M%SZ")
        backup = backup_path_for(db_path, timestamp=stamp)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"backup")
    _prune_old_backups(db_path, keep=MAX_BACKUPS)
    survivors = list_backups(db_path)
    assert len(survivors) == MAX_BACKUPS
