"""Unit tests for the generic migration runner."""

from __future__ import annotations

import threading
from pathlib import Path

import duckdb
import pytest
from filelock import FileLock, Timeout

from hydromodpy.core.migrations import (
    DEFAULT_COMPONENT,
    Migration,
    MigrationDiscoveryError,
    MigrationExecutionError,
    SchemaIntegrityError,
    apply_migration,
    apply_migrations,
    current_version,
    discover_migrations,
    ensure_schema,
    target_version,
)
from hydromodpy.core.migrations.runner import repair_hint_for


def _write(versions_dir: Path, version: int, slug: str, sql: str) -> Path:
    path = versions_dir / f"{version:04d}_{slug}.sql"
    path.write_text(sql, encoding="utf-8")
    return path


@pytest.fixture
def versions_dir(tmp_path: Path) -> Path:
    """Empty directory in which tests drop ``NNNN_*.sql`` migrations."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Filesystem path for a brand-new DuckDB database."""
    return tmp_path / "store.duckdb"


def test_apply_migrations_initial_run(versions_dir: Path, db_path: Path) -> None:
    """First run creates the DB, applies all scripts and returns the new version."""
    _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")
    _write(versions_dir, 2, "beta", "CREATE TABLE beta (id INTEGER);")

    new_version = apply_migrations(db_path, versions_dir)

    assert new_version == 2
    assert db_path.is_file()
    connection = duckdb.connect(str(db_path))
    try:
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('alpha', 'beta')"
            ).fetchall()
        }
        assert tables == {"alpha", "beta"}
        assert current_version(connection) == 2
    finally:
        connection.close()


def test_apply_migrations_is_idempotent(versions_dir: Path, db_path: Path) -> None:
    """Running twice in a row applies nothing the second time."""
    _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")

    first = apply_migrations(db_path, versions_dir)
    second = apply_migrations(db_path, versions_dir)

    assert first == second == 1


def test_apply_migrations_returns_zero_when_dir_empty(versions_dir: Path, db_path: Path) -> None:
    """A directory with no migration files yields version 0."""
    assert apply_migrations(db_path, versions_dir) == 0


def test_apply_migrations_creates_parent_directory(tmp_path: Path, versions_dir: Path) -> None:
    """Missing parent directories of ``db_path`` are created on the fly."""
    _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")
    nested = tmp_path / "nested" / "deeper" / "store.duckdb"

    apply_migrations(nested, versions_dir)

    assert nested.is_file()


def test_apply_migrations_serialises_concurrent_callers(versions_dir: Path, db_path: Path) -> None:
    """A second caller blocks until the file lock is released."""
    _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")

    holder = FileLock(f"{db_path}.lock")
    holder.acquire()
    try:
        with pytest.raises(Timeout):
            apply_migrations(db_path, versions_dir, lock_timeout=0.2)
    finally:
        holder.release()

    # Once released, the migration completes normally.
    assert apply_migrations(db_path, versions_dir) == 1


def test_apply_migrations_releases_lock_on_failure(versions_dir: Path, db_path: Path) -> None:
    """A failing migration releases the lock so the next caller can run."""
    _write(versions_dir, 1, "broken", "CREAT BROKEN SYNTAX")

    with pytest.raises(MigrationExecutionError):
        apply_migrations(db_path, versions_dir)

    # The lock must be released even though the migration failed.
    with FileLock(f"{db_path}.lock", timeout=0.1):
        pass


def test_apply_migrations_component_isolates_versions(versions_dir: Path, db_path: Path) -> None:
    """Two components evolve their version counters independently."""
    catalog_dir = versions_dir / "catalog"
    index_dir = versions_dir / "index"
    catalog_dir.mkdir()
    index_dir.mkdir()
    _write(catalog_dir, 1, "a", "CREATE TABLE catalog_a (id INTEGER);")
    _write(index_dir, 1, "b", "CREATE TABLE index_b (id INTEGER);")
    _write(index_dir, 2, "c", "CREATE TABLE index_c (id INTEGER);")

    assert apply_migrations(db_path, catalog_dir, component="catalog") == 1
    assert apply_migrations(db_path, index_dir, component="index") == 2

    connection = duckdb.connect(str(db_path))
    try:
        assert current_version(connection, component="catalog") == 1
        assert current_version(connection, component="index") == 2
    finally:
        connection.close()


def test_apply_migrations_runs_in_parallel_threads(versions_dir: Path, db_path: Path) -> None:
    """Two threads racing the same DB end up with a consistent state."""
    _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")
    _write(versions_dir, 2, "beta", "CREATE TABLE beta (id INTEGER);")

    results: list[int] = []
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            results.append(apply_migrations(db_path, versions_dir, lock_timeout=10.0))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=runner) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results == [2, 2, 2, 2]


def test_discover_migrations_rejects_gap(versions_dir: Path) -> None:
    """Missing intermediate versions raise on discovery."""
    _write(versions_dir, 1, "a", "-- a")
    _write(versions_dir, 3, "c", "-- c")

    with pytest.raises(MigrationDiscoveryError, match="Gap"):
        discover_migrations(versions_dir)


def test_discover_migrations_rejects_duplicate(versions_dir: Path) -> None:
    """Two files at the same version raise."""
    (versions_dir / "0001_a.sql").write_text("-- a\n", encoding="utf-8")
    (versions_dir / "0001_b.sql").write_text("-- b\n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError, match="Duplicate"):
        discover_migrations(versions_dir)


def test_discover_migrations_rejects_malformed_filename(versions_dir: Path) -> None:
    """A filename outside ``<NNNN>_<slug>.sql`` raises."""
    (versions_dir / "v1_init.sql").write_text("-- bad\n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError, match="Malformed"):
        discover_migrations(versions_dir)


def test_ensure_schema_rejects_checksum_drift(versions_dir: Path) -> None:
    """An applied migration whose disk content changed raises on the next run."""
    sql_path = _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")
    connection = duckdb.connect(":memory:")
    try:
        ensure_schema(connection, versions_dir=versions_dir, component=DEFAULT_COMPONENT)
        sql_path.write_text("CREATE TABLE alpha_renamed (id INTEGER);", encoding="utf-8")
        with pytest.raises(SchemaIntegrityError, match="Checksum mismatch"):
            ensure_schema(connection, versions_dir=versions_dir, component=DEFAULT_COMPONENT)
    finally:
        connection.close()


def test_checksum_drift_names_the_repair_command(versions_dir: Path) -> None:
    """The message must carry the fix: a stale checksum is the first-run-after-upgrade trap."""
    sql_path = _write(versions_dir, 1, "alpha", "CREATE TABLE alpha (id INTEGER);")
    connection = duckdb.connect(":memory:")
    try:
        ensure_schema(connection, versions_dir=versions_dir, component="catalog")
        sql_path.write_text("CREATE TABLE alpha_renamed (id INTEGER);", encoding="utf-8")
        with pytest.raises(SchemaIntegrityError, match="hmp catalog reindex"):
            ensure_schema(connection, versions_dir=versions_dir, component="catalog")
    finally:
        connection.close()


def test_every_component_has_a_repair_hint() -> None:
    assert "hmp catalog reindex" in repair_hint_for("catalog")
    assert "hmp workspace register" in repair_hint_for("index")
    assert "restore" in repair_hint_for("data_cache")
    assert "delete the widgets database" in repair_hint_for("widgets")


def test_apply_migration_rolls_back_on_failure(versions_dir: Path) -> None:
    """A broken SQL body leaves ``schema_migrations`` untouched."""
    sql_path = _write(versions_dir, 1, "broken", "CREAT BROKEN")
    connection = duckdb.connect(":memory:")
    try:
        ensure_schema(connection, versions_dir=versions_dir, component=DEFAULT_COMPONENT)
    except MigrationExecutionError:
        pass
    try:
        bad = Migration(version=99, slug="broken", sql_path=sql_path)
        with pytest.raises(MigrationExecutionError):
            apply_migration(connection, bad)
        rows = connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 99"
        ).fetchall()
        assert rows == []
    finally:
        connection.close()


def test_target_version_matches_highest_disk_version(versions_dir: Path) -> None:
    """``target_version`` reflects the highest on-disk migration."""
    _write(versions_dir, 1, "a", "-- a")
    _write(versions_dir, 2, "b", "-- b")
    _write(versions_dir, 3, "c", "-- c")

    assert target_version(versions_dir) == 3
    assert [m.version for m in discover_migrations(versions_dir)] == [1, 2, 3]


def test_migration_model_forbids_extra_fields(versions_dir: Path) -> None:
    """The Pydantic record sets ``extra='forbid'``."""
    sql_path = _write(versions_dir, 1, "alpha", "-- alpha")
    with pytest.raises(Exception, match="extra"):
        Migration(
            version=1,
            slug="alpha",
            sql_path=sql_path,
            unknown="forbidden",
        )
