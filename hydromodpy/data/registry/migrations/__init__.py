"""Data cache DuckDB schema migrations.

Thin wrapper that binds the generic migration runner from
``hydromodpy.core.migrations`` to the bundled SQL directory and to the
``"data_cache"`` component name.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.migrations import (
    Migration,
    MigrationDiscoveryError,
    MigrationError,
    MigrationExecutionError,
    SchemaIntegrityError,
)
from hydromodpy.core.migrations import apply_migration as _apply_migration
from hydromodpy.core.migrations import apply_migrations as _apply_migrations
from hydromodpy.core.migrations import current_version as _current_version
from hydromodpy.core.migrations import discover_migrations as _discover_migrations
from hydromodpy.core.migrations import ensure_schema as _ensure_schema
from hydromodpy.core.migrations import target_version as _target_version

if TYPE_CHECKING:
    import duckdb

DATA_CACHE_COMPONENT = "data_cache"

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def ensure_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path | None = None,
) -> None:
    """Bring the data cache DuckDB schema up to the latest bundled version."""
    resolved_versions_dir = versions_dir if versions_dir is not None else _MIGRATIONS_DIR
    _adopt_legacy_v1_schema(connection, versions_dir=resolved_versions_dir)
    _ensure_schema(
        connection,
        versions_dir=resolved_versions_dir,
        component=DATA_CACHE_COMPONENT,
    )


def apply_migrations(db_path: Path, versions_dir: Path | None = None) -> int:
    """Open ``db_path`` and apply pending data cache migrations."""
    return _apply_migrations(
        db_path,
        versions_dir if versions_dir is not None else _MIGRATIONS_DIR,
        component=DATA_CACHE_COMPONENT,
    )


def current_version(connection: duckdb.DuckDBPyConnection) -> int:
    """Return the highest applied data cache migration version (0 if none)."""
    return _current_version(connection, component=DATA_CACHE_COMPONENT)


def target_version(versions_dir: Path | None = None) -> int:
    """Return the highest data cache migration version present on disk."""
    return _target_version(versions_dir if versions_dir is not None else _MIGRATIONS_DIR)


def discover_migrations(versions_dir: Path | None = None) -> list[Migration]:
    """Discover data cache migrations under ``versions_dir`` or the bundled dir."""
    return _discover_migrations(versions_dir if versions_dir is not None else _MIGRATIONS_DIR)


def apply_migration(connection: duckdb.DuckDBPyConnection, migration: Migration) -> None:
    """Apply one data cache migration in a transaction."""
    _apply_migration(connection, migration, component=DATA_CACHE_COMPONENT)


def _adopt_legacy_v1_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path,
) -> None:
    """Record the initial migration for pre-migration data-cache databases.

    Early V1 data caches already contained the final ``0001_initial`` tables
    and sometimes an older ``_schema_version`` row, but no
    ``schema_migrations`` ledger. Without this adoption step, the generic
    runner tries to execute ``0001_initial.sql`` again and fails because
    ``entries`` already exists.
    """

    _ensure_system_tables_compatible(connection)
    if _current_version(connection, component=DATA_CACHE_COMPONENT) > 0:
        return
    if not _legacy_data_cache_schema_present(connection):
        return
    migrations = _discover_migrations(versions_dir)
    if not migrations or migrations[0].version != 1:
        return
    migration = migrations[0]
    connection.execute(
        """
        INSERT INTO schema_migrations (version, component, slug, checksum)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (component, version) DO NOTHING
        """,
        [migration.version, DATA_CACHE_COMPONENT, migration.slug, migration.checksum],
    )
    connection.execute(
        """
        INSERT INTO _schema_version (component, version, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (component) DO UPDATE
            SET version = excluded.version,
                updated_at = excluded.updated_at
        """,
        [DATA_CACHE_COMPONENT, migration.version],
    )


def _ensure_system_tables_compatible(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER NOT NULL,
            component   VARCHAR NOT NULL,
            slug        VARCHAR NOT NULL,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            checksum    VARCHAR NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    if not _table_exists(connection, "_schema_version"):
        connection.execute(
            """
            CREATE TABLE _schema_version (
                component   VARCHAR PRIMARY KEY,
                version     INTEGER NOT NULL,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return

    columns = _table_columns(connection, "_schema_version")
    if {"component", "version", "updated_at"} <= columns:
        return

    timestamp_expr = "CURRENT_TIMESTAMP"
    if "applied_at" in columns:
        timestamp_expr = "COALESCE(applied_at, CURRENT_TIMESTAMP)"
    connection.execute(
        f"""
        CREATE TEMP TABLE _schema_version_rows AS
        SELECT
            CAST(component AS VARCHAR) AS component,
            TRY_CAST(version AS INTEGER) AS version,
            {timestamp_expr} AS updated_at
        FROM _schema_version
        WHERE TRY_CAST(version AS INTEGER) IS NOT NULL
        """
    )
    connection.execute("DROP TABLE _schema_version")
    connection.execute(
        """
        CREATE TABLE _schema_version (
            component   VARCHAR PRIMARY KEY,
            version     INTEGER NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO _schema_version (component, version, updated_at)
        SELECT component, version, updated_at FROM _schema_version_rows
        """
    )
    connection.execute("DROP TABLE _schema_version_rows")


def _legacy_data_cache_schema_present(connection: duckdb.DuckDBPyConnection) -> bool:
    required = {
        "entries",
        "api_coverage",
        "artifacts",
        "provenance",
        "stations",
        "coverage",
        "failures",
        "validation_reports",
    }
    return required <= set(_table_names(connection))


def _table_exists(connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and int(row[0]) > 0)


def _table_names(connection: duckdb.DuckDBPyConnection) -> list[str]:
    rows = connection.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main'
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_columns(connection: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {str(row[1]) for row in rows}


__all__ = [
    "DATA_CACHE_COMPONENT",
    "Migration",
    "MigrationDiscoveryError",
    "MigrationError",
    "MigrationExecutionError",
    "SchemaIntegrityError",
    "apply_migration",
    "apply_migrations",
    "current_version",
    "discover_migrations",
    "ensure_schema",
    "target_version",
]
