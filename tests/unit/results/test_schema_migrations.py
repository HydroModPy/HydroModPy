"""Unit tests for the Alembic-like catalog schema migration runner."""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.migrations import Migration
from hydromodpy.results.catalog.migrations import (
    CATALOG_COMPONENT,
    MigrationDiscoveryError,
    MigrationExecutionError,
    SchemaIntegrityError,
    apply_migration,
    current_version,
    discover_migrations,
    ensure_schema,
    target_version,
)


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    """Fresh in-memory DuckDB connection, closed at teardown."""
    connection = duckdb.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def _write_migration(versions_dir: Path, version: int, slug: str, sql: str) -> Path:
    path = versions_dir / f"{version:04d}_{slug}.sql"
    path.write_text(sql, encoding="utf-8")
    return path


def test_ensure_schema_on_empty_db_creates_system_tables_and_applies_initial(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """First call seeds system tables and registers the bundled migrations."""
    assert current_version(conn) == 0

    ensure_schema(conn)

    tables = {
        name
        for (name,) in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('schema_migrations', '_schema_version')"
        ).fetchall()
    }
    assert tables == {"schema_migrations", "_schema_version"}

    rows = conn.execute("SELECT version, slug FROM schema_migrations ORDER BY version").fetchall()
    assert rows == [
        (1, "initial"),
        (2, "audit_hash_chain"),
        (3, "retention_policies"),
        (4, "workflow_events"),
        (5, "drop_simulation_heartbeat"),
        (6, "drop_simulation_heartbeat_column"),
        (7, "simulation_lifecycle"),
        (8, "trash_original_status"),
    ]

    version_rows = conn.execute("SELECT component, version FROM _schema_version").fetchall()
    assert version_rows == [(CATALOG_COMPONENT, 8)]

    assert current_version(conn) == 8
    assert target_version() == 8


def test_ensure_schema_is_idempotent(conn: duckdb.DuckDBPyConnection) -> None:
    """A second call applies nothing and preserves the original applied_at."""
    ensure_schema(conn)
    first_applied_at = conn.execute(
        "SELECT version, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()

    time.sleep(0.01)
    ensure_schema(conn)

    rows = conn.execute(
        "SELECT version, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert len(rows) == 8
    assert rows == first_applied_at


def test_apply_in_order(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    """Three migrations apply in ascending order with chronological timestamps."""
    _write_migration(tmp_path, 1, "a", "CREATE TABLE t1 (id INTEGER);")
    _write_migration(tmp_path, 2, "b", "CREATE TABLE t2 (id INTEGER);")
    _write_migration(tmp_path, 3, "c", "CREATE TABLE t3 (id INTEGER);")

    ensure_schema(conn, versions_dir=tmp_path)

    rows = conn.execute(
        "SELECT version, slug, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [(v, s) for v, s, _ in rows] == [(1, "a"), (2, "b"), (3, "c")]
    timestamps = [t for _, _, t in rows]
    assert timestamps == sorted(timestamps)

    user_tables = {
        name
        for (name,) in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('t1', 't2', 't3')"
        ).fetchall()
    }
    assert user_tables == {"t1", "t2", "t3"}

    assert current_version(conn) == 3
    assert target_version(tmp_path) == 3
    assert [m.version for m in discover_migrations(tmp_path)] == [1, 2, 3]


def test_rejects_gap(tmp_path: Path) -> None:
    """Missing intermediate versions fail discovery."""
    _write_migration(tmp_path, 1, "a", "CREATE TABLE t1 (id INTEGER);")
    _write_migration(tmp_path, 3, "c", "CREATE TABLE t3 (id INTEGER);")

    with pytest.raises(MigrationDiscoveryError, match="Gap"):
        discover_migrations(tmp_path)


def test_rejects_checksum_mismatch(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    """Editing an applied script after the fact must raise on re-check."""
    sql_path = _write_migration(tmp_path, 1, "a", "CREATE TABLE t1 (id INTEGER);")
    ensure_schema(conn, versions_dir=tmp_path)

    sql_path.write_text("CREATE TABLE t1_renamed (id INTEGER);", encoding="utf-8")

    with pytest.raises(SchemaIntegrityError, match="Checksum mismatch"):
        ensure_schema(conn, versions_dir=tmp_path)


def test_rejects_invalid_sql(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    """Broken SQL bubbles up and leaves the migrations table clean."""
    _write_migration(tmp_path, 1, "broken", "CREAT BROKEN SYNTAX")

    with pytest.raises(MigrationExecutionError):
        ensure_schema(conn, versions_dir=tmp_path)

    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert rows == []
    assert current_version(conn) == 0


def test_rejects_duplicate_version(tmp_path: Path) -> None:
    """Two files at the same version raise a discovery error."""
    (tmp_path / "0001_a.sql").write_text("-- a\n", encoding="utf-8")
    (tmp_path / "0001_b.sql").write_text("-- b\n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError, match="Duplicate"):
        discover_migrations(tmp_path)


def test_rejects_malformed_filename(tmp_path: Path) -> None:
    """Filenames that don't match ``<NNNN>_<slug>.sql`` raise a discovery error."""
    (tmp_path / "v1_init.sql").write_text("-- bad\n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError, match="Malformed"):
        discover_migrations(tmp_path)


def test_migration_model_rejects_extra_fields(tmp_path: Path) -> None:
    """The :class:`Migration` Pydantic model enforces ``extra='forbid'``."""
    sql_path = _write_migration(tmp_path, 1, "a", "-- x")
    with pytest.raises(Exception, match="extra"):
        Migration(
            version=1,
            slug="a",
            sql_path=sql_path,
            unknown="forbidden",
        )


def test_lifecycle_migration_applies_on_populated_catalog(tmp_path: Path) -> None:
    """Migration 0007 must apply when ``simulations`` already holds rows.

    Regression: 0007 backfills ``name_stem``/``version_int`` with an
    ``UPDATE simulations`` and then builds ``ix_sim_name_stem`` in the same
    transaction. DuckDB rejects ``CREATE INDEX`` on a pre-existing table that
    has outstanding row updates, so the migration crashed on any non-empty
    catalog. An empty table makes the UPDATE a no-op, which hid the bug from
    the empty-DB migration tests.
    """
    import shutil

    from hydromodpy.results.catalog.migrations import MIGRATIONS_DIR

    # Stage migrations 1..6 (pre-lifecycle) in an isolated dir, reach v6.
    pre = tmp_path / "pre"
    pre.mkdir()
    for migration in discover_migrations(MIGRATIONS_DIR):
        if migration.version <= 6:
            shutil.copy(migration.sql_path, pre / migration.sql_path.name)

    db_path = tmp_path / "catalog.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        ensure_schema(conn, versions_dir=pre)
        assert current_version(conn) == 6

        # Seed a real simulation row and an audit row so the 0007 backfill and
        # the audit_log table rebuild both operate on outstanding data.
        conn.execute(
            "INSERT INTO simulations "
            "(sim_id, name, project, solver_id, status_id, zarr_path, "
            " zarr_packed, storage_basename) VALUES "
            "(gen_random_uuid(), 'baseline.v2', 'demo', 1, 3, 's.zarr', "
            " false, 'demo__abcd1234')"
        )
        conn.execute(
            "INSERT INTO audit_log (event_id, actor, actor_kind, event_type, payload) "
            "VALUES (gen_random_uuid(), 'tester', 'cli', 'sim.register', '{}')"
        )

        # The full bundled dir applies the pending 0007/0008 on the populated DB.
        ensure_schema(conn)

        assert current_version(conn) == 8
        stem, version_int = conn.execute(
            "SELECT name_stem, version_int FROM simulations"
        ).fetchone()
        assert stem == "baseline"
        assert version_int == 2
        # The audit_log table is rebuilt by 0007; the seeded row must survive
        # the verbatim copy (the hash chain depends on it).
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE event_type = 'sim.register' AND actor = 'tester'"
            ).fetchone()[0]
            == 1
        )
        index_names = {
            name
            for (name,) in conn.execute(
                "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'simulations'"
            ).fetchall()
        }
        assert "ix_sim_name_stem" in index_names
    finally:
        conn.close()


def test_apply_migration_rolls_back_on_failure(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    """``apply_migration`` rolls back when the SQL fails."""
    ensure_schema(conn, versions_dir=tmp_path)
    sql_path = _write_migration(tmp_path, 1, "broken", "CREAT BROKEN")
    bad = Migration(version=99, slug="broken", sql_path=sql_path)

    with pytest.raises(MigrationExecutionError):
        apply_migration(conn, bad)

    rows = conn.execute("SELECT version FROM schema_migrations WHERE version = 99").fetchall()
    assert rows == []
