"""Alembic-like migration runner for the catalog DuckDB.

The runner discovers ``<NNNN>_<slug>.sql`` scripts under ``versions_dir``,
records each application in ``schema_migrations`` and keeps the
``_schema_version`` row for the ``catalog`` component in sync. It is
idempotent: rerunning :func:`ensure_schema` on an up-to-date database
applies nothing and only verifies checksum integrity.
"""

from __future__ import annotations

import hashlib
import re
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from hydromodpy.results.catalog.migrations.errors import (
    MigrationDiscoveryError,
    MigrationExecutionError,
    SchemaIntegrityError,
)

if TYPE_CHECKING:
    import duckdb

CATALOG_COMPONENT = "catalog"

_VERSIONS_DIR = Path(__file__).resolve().parent / "versions"
_FILENAME_RE = re.compile(r"^(?P<version>\d{4})_(?P<slug>[a-z0-9][a-z0-9_]*)\.sql$")

_SYSTEM_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    slug        VARCHAR NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum    VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS _schema_version (
    component   VARCHAR PRIMARY KEY,
    version     INTEGER NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Migration(BaseModel):
    """One ``<NNNN>_<slug>.sql`` migration script on disk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    slug: str
    sql_path: Path

    @cached_property
    def upgrade_sql(self) -> str:
        """SQL body of the migration, read once from disk."""
        return self.sql_path.read_text(encoding="utf-8")

    @cached_property
    def checksum(self) -> str:
        """SHA-256 of the SQL body, used to detect tampering."""
        return _sha256(self.upgrade_sql)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover_migrations(versions_dir: Path | None = None) -> list[Migration]:
    """Return migrations sorted by version, rejecting gaps and duplicates."""
    root = versions_dir if versions_dir is not None else _VERSIONS_DIR
    if not root.is_dir():
        raise MigrationDiscoveryError(f"Migrations directory missing: {root}")

    migrations: list[Migration] = []
    seen: dict[int, Path] = {}
    for path in sorted(root.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if match is None:
            raise MigrationDiscoveryError(
                f"Malformed migration filename {path.name!r}; expected '<NNNN>_<slug>.sql'"
            )
        version = int(match.group("version"))
        if version in seen:
            raise MigrationDiscoveryError(
                f"Duplicate migration version {version:04d}: {seen[version].name} vs {path.name}"
            )
        seen[version] = path
        migrations.append(Migration(version=version, slug=match.group("slug"), sql_path=path))

    migrations.sort(key=lambda m: m.version)
    if not migrations:
        return migrations

    expected = 1
    for migration in migrations:
        if migration.version != expected:
            raise MigrationDiscoveryError(
                f"Gap in migration versions: expected {expected:04d}, "
                f"got {migration.version:04d} ({migration.sql_path.name})"
            )
        expected += 1

    return migrations


def list_migrations(versions_dir: Path | None = None) -> list[Migration]:
    """Public alias for :func:`discover_migrations`."""
    return discover_migrations(versions_dir)


def current_version(connection: duckdb.DuckDBPyConnection) -> int:
    """Return the highest applied version, or 0 if none."""
    if not _has_system_tables(connection):
        return 0
    row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0]) if row is not None else 0


def target_version(versions_dir: Path | None = None) -> int:
    """Return the highest migration version present on disk."""
    migrations = discover_migrations(versions_dir)
    return migrations[-1].version if migrations else 0


def apply_migration(
    connection: duckdb.DuckDBPyConnection,
    migration: Migration,
) -> None:
    """Apply one migration in a transaction and record it."""
    sql = migration.upgrade_sql
    checksum = migration.checksum
    connection.execute("BEGIN TRANSACTION")
    try:
        if sql.strip():
            connection.execute(sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, slug, checksum) VALUES (?, ?, ?)",
            [migration.version, migration.slug, checksum],
        )
        connection.execute(
            """
            INSERT INTO _schema_version (component, version, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (component) DO UPDATE
                SET version = excluded.version,
                    updated_at = excluded.updated_at
            """,
            [CATALOG_COMPONENT, migration.version],
        )
        connection.execute("COMMIT")
    except Exception as exc:
        connection.execute("ROLLBACK")
        raise MigrationExecutionError(
            f"Failed to apply migration {migration.version:04d}_{migration.slug}: {exc}"
        ) from exc


def ensure_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path | None = None,
) -> None:
    """Bring the catalog schema up to the highest available version.

    Creates the two system tables if missing, applies every pending
    migration in order, and verifies checksum integrity for migrations
    already recorded. Safe to call repeatedly.
    """
    _create_system_tables(connection)
    migrations = discover_migrations(versions_dir)
    applied = _load_applied(connection)

    for migration in migrations:
        recorded = applied.get(migration.version)
        if recorded is None:
            apply_migration(connection, migration)
            continue
        if recorded != migration.checksum:
            raise SchemaIntegrityError(
                f"Checksum mismatch for migration {migration.version:04d}_{migration.slug}: "
                f"stored {recorded!r}, disk {migration.checksum!r}"
            )


def _create_system_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_SYSTEM_TABLES_DDL)


def _has_system_tables(connection: duckdb.DuckDBPyConnection) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name IN ('schema_migrations', '_schema_version')
        """
    ).fetchone()
    return bool(row and int(row[0]) == 2)


def _load_applied(connection: duckdb.DuckDBPyConnection) -> dict[int, str]:
    rows = connection.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {int(version): str(checksum) for version, checksum in rows}
