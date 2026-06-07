"""Regression tests for ``ensure_schema_safe``.

Three v1 fixtures (empty / single sim / multi sim) round-trip through the
auto-boot path: pre-migration backup is written, post-migration the schema
sits at the latest version, seeded simulations survive, and restoring the
backup yields a working v1 catalog again.

Also covers the opt-out (``HMP_AUTO_MIGRATE=0``) and the failure path
(corrupt migration triggers a restore).
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
def test_round_trip_v1_to_latest(tmp_path: Path, stem: str) -> None:
    """Every v1 fixture migrates to the latest version with a backup written."""
    db_path = copy_fixture(stem, tmp_path)
    pre_count = _count_simulations(db_path)
    pre_backups = list_backups(db_path)

    conn = duckdb.connect(str(db_path))
    try:
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

    new_backups = [p for p in list_backups(db_path) if p not in pre_backups]
    assert len(new_backups) == 1, "auto-boot must drop exactly one backup before migrating"


@pytest.mark.parametrize("stem", ALL_FIXTURES[:1])
def test_opt_out_disables_migration(
    tmp_path: Path, stem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``HMP_AUTO_MIGRATE=0`` blocks the migration without touching the file."""
    db_path = copy_fixture(stem, tmp_path)
    monkeypatch.setenv("HMP_AUTO_MIGRATE", "0")
    conn = duckdb.connect(str(db_path))
    try:
        with pytest.raises(AutoMigrationDisabled):
            ensure_schema_safe(
                conn,
                db_path=db_path,
                versions_dir=MIGRATIONS_DIR,
                component=CATALOG_COMPONENT,
            )
        # File stays at v1.
        assert current_version(conn) == 1
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


def test_restore_on_migration_failure(tmp_path: Path) -> None:
    """A simulated migration failure rolls the file back to the v1 backup."""
    from hydromodpy.core.migrations import auto_boot as auto_boot_mod

    db_path = copy_fixture("single_sim", tmp_path)
    pre_count = _count_simulations(db_path)

    real_ensure = auto_boot_mod.ensure_schema

    def _boom(connection, *args, **kwargs) -> None:
        # Mutate through DuckDB itself so the failure simulation is portable
        # even on platforms that deny raw writes to an open database file.
        connection.execute("DROP TABLE IF EXISTS simulations")
        raise RuntimeError("simulated migration crash")

    auto_boot_mod.ensure_schema = _boom  # type: ignore[assignment]
    try:
        conn = duckdb.connect(str(db_path))
        try:
            with pytest.raises(RuntimeError, match="simulated"):
                ensure_schema_safe(
                    conn,
                    db_path=db_path,
                    versions_dir=MIGRATIONS_DIR,
                    component=CATALOG_COMPONENT,
                )
        finally:
            try:
                conn.close()
            except Exception:
                pass
    finally:
        auto_boot_mod.ensure_schema = real_ensure

    # The file must be back at v1 with the seeded row intact.
    assert _count_simulations(db_path) == pre_count
