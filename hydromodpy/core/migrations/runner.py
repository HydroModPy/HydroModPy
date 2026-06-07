"""Alembic-like migration runner generic over DuckDB databases.

The runner discovers ``<NNNN>_<slug>.sql`` scripts under ``versions_dir``,
records each application in ``schema_migrations`` and keeps one row of
``_schema_version`` per component in sync. It is idempotent: rerunning
:func:`ensure_schema` on an up-to-date database applies nothing and only
verifies checksum integrity.

The same runner serves multiple components by parametrizing
``component`` (e.g. ``"catalog"`` for project catalogs, ``"index"`` for
the machine-wide global index).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.migrations.errors import (
    MigrationDiscoveryError,
    MigrationExecutionError,
    SchemaIntegrityError,
)

if TYPE_CHECKING:
    import duckdb

DEFAULT_COMPONENT = "catalog"
DEFAULT_LOCK_TIMEOUT = 30.0

_FILENAME_RE = re.compile(r"^(?P<version>\d{4})_(?P<slug>[a-z0-9][a-z0-9_]*)\.sql$")

_SYSTEM_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER NOT NULL,
    component   VARCHAR NOT NULL,
    slug        VARCHAR NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum    VARCHAR NOT NULL,
    PRIMARY KEY (component, version)
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


def discover_migrations(versions_dir: Path) -> list[Migration]:
    """Return migrations sorted by version, rejecting gaps and duplicates."""
    if not versions_dir.is_dir():
        raise MigrationDiscoveryError(f"Migrations directory missing: {versions_dir}")

    migrations: list[Migration] = []
    seen: dict[int, Path] = {}
    for path in sorted(versions_dir.glob("*.sql")):
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


def list_migrations(versions_dir: Path) -> list[Migration]:
    """Public alias for :func:`discover_migrations`."""
    return discover_migrations(versions_dir)


def current_version(
    connection: duckdb.DuckDBPyConnection,
    *,
    component: str = DEFAULT_COMPONENT,
) -> int:
    """Return the highest applied version for ``component``, 0 if none."""
    if not _has_system_tables(connection):
        return 0
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations WHERE component = ?",
        [component],
    ).fetchone()
    return int(row[0]) if row is not None else 0


def target_version(versions_dir: Path) -> int:
    """Return the highest migration version present on disk."""
    migrations = discover_migrations(versions_dir)
    return migrations[-1].version if migrations else 0


def apply_migration(
    connection: duckdb.DuckDBPyConnection,
    migration: Migration,
    *,
    component: str = DEFAULT_COMPONENT,
    post_apply: Callable[[duckdb.DuckDBPyConnection, Migration, str], None] | None = None,
) -> None:
    """Apply one migration in a transaction and record it for ``component``.

    ``post_apply`` is invoked after a successful COMMIT and is best-effort:
    any exception it raises is swallowed (used to emit audit events from
    callers that depend on a higher layer like ``results``).
    """
    sql = migration.upgrade_sql
    checksum = migration.checksum
    connection.execute("BEGIN TRANSACTION")
    try:
        if sql.strip():
            connection.execute(sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, component, slug, checksum) "
            "VALUES (?, ?, ?, ?)",
            [migration.version, component, migration.slug, checksum],
        )
        connection.execute(
            """
            INSERT INTO _schema_version (component, version, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (component) DO UPDATE
                SET version = excluded.version,
                    updated_at = excluded.updated_at
            """,
            [component, migration.version],
        )
        connection.execute("COMMIT")
    except Exception as exc:
        connection.execute("ROLLBACK")
        raise MigrationExecutionError(
            f"Failed to apply migration {migration.version:04d}_{migration.slug} "
            f"for component {component!r}: {exc}"
        ) from exc

    if post_apply is not None:
        try:
            post_apply(connection, migration, component)
        except Exception:
            return


def ensure_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path,
    component: str = DEFAULT_COMPONENT,
    post_apply: Callable[[duckdb.DuckDBPyConnection, Migration, str], None] | None = None,
) -> None:
    """Bring ``component`` up to the highest available version.

    Creates the two system tables if missing, applies every pending
    migration in order, and verifies checksum integrity for migrations
    already recorded. Safe to call repeatedly.
    """
    _create_system_tables(connection)
    migrations = discover_migrations(versions_dir)
    applied = _load_applied(connection, component=component)

    for migration in migrations:
        recorded = applied.get(migration.version)
        if recorded is None:
            apply_migration(connection, migration, component=component, post_apply=post_apply)
            continue
        if recorded != migration.checksum:
            raise SchemaIntegrityError(
                f"Checksum mismatch for migration {migration.version:04d}_{migration.slug} "
                f"({component}): stored {recorded!r}, disk {migration.checksum!r}"
            )


def apply_migrations(
    db_path: Path,
    migrations_dir: Path,
    *,
    component: str = DEFAULT_COMPONENT,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> int:
    """Open ``db_path``, apply pending migrations, return the new version.

    Acquires a :class:`filelock.FileLock` on ``<db_path>.lock`` so concurrent
    callers serialise their migration runs against the same physical database.
    Creates the parent directory of ``db_path`` if missing.
    """
    import duckdb

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(f"{db_path}.lock", timeout=lock_timeout)
    with lock:
        connection = duckdb.connect(str(db_path))
        try:
            ensure_schema(connection, versions_dir=migrations_dir, component=component)
            return current_version(connection, component=component)
        finally:
            connection.close()


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


def _load_applied(
    connection: duckdb.DuckDBPyConnection,
    *,
    component: str,
) -> dict[int, str]:
    rows = connection.execute(
        "SELECT version, checksum FROM schema_migrations WHERE component = ?",
        [component],
    ).fetchall()
    return {int(version): str(checksum) for version, checksum in rows}
