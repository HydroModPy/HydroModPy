"""Catalog DuckDB schema migrations.

Thin wrapper that binds the generic migration runner from
``hydromodpy.core.migrations`` to the bundled SQL directory and to the
``"catalog"`` component name.
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
from hydromodpy.core.migrations import ensure_schema_safe as _ensure_schema_safe
from hydromodpy.core.migrations import target_version as _target_version

if TYPE_CHECKING:
    import duckdb

CATALOG_COMPONENT = "catalog"

MIGRATIONS_DIR = Path(__file__).resolve().parent


def _emit_migrate_event(
    connection: duckdb.DuckDBPyConnection,
    migration: Migration,
    component: str,
) -> None:
    """Best-effort ``migrate`` audit row after a catalog migration commits."""
    from hydromodpy.results.catalog.audit import emit_audit_event

    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'audit_log'"
        ).fetchone()
    except Exception:
        return
    if not row or int(row[0]) == 0:
        return
    emit_audit_event(
        connection,
        event_type="migrate",
        actor_kind="system",
        payload={
            "component": component,
            "version": migration.version,
            "slug": migration.slug,
            "checksum": migration.checksum,
        },
    )


def ensure_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    """Bring the catalog DuckDB schema up to the latest bundled version.

    Routes through :func:`hydromodpy.core.migrations.ensure_schema_safe` so
    every catalog bootstrap acquires the file lock, takes an atomic backup
    before any DDL, and restores it on failure. ``db_path`` is resolved
    from the connection when omitted so callers that already opened the
    file do not need to thread the path manually.
    """
    if db_path is None:
        db_path = _resolve_db_path_from_connection(connection)
    _ensure_schema_safe(
        connection,
        db_path=db_path,
        versions_dir=versions_dir if versions_dir is not None else MIGRATIONS_DIR,
        component=CATALOG_COMPONENT,
        post_apply=_emit_migrate_event,
    )


def _resolve_db_path_from_connection(
    connection: duckdb.DuckDBPyConnection,
) -> Path:
    """Best-effort discovery of the on-disk catalog path from a live connection."""
    try:
        rows = connection.execute("PRAGMA database_list").fetchall()
    except Exception:
        return Path("memory.duckdb")
    for row in rows:
        candidate = row[2] if len(row) >= 3 else None
        if candidate and candidate != ":memory:":
            return Path(str(candidate))
    return Path("memory.duckdb")


def apply_migrations(db_path: Path, versions_dir: Path | None = None) -> int:
    """Open ``db_path`` and apply pending catalog migrations."""
    return _apply_migrations(
        db_path,
        versions_dir if versions_dir is not None else MIGRATIONS_DIR,
        component=CATALOG_COMPONENT,
    )


def current_version(connection: duckdb.DuckDBPyConnection) -> int:
    """Return the highest applied catalog migration version (0 if none)."""
    return _current_version(connection, component=CATALOG_COMPONENT)


def target_version(versions_dir: Path | None = None) -> int:
    """Return the highest catalog migration version present on disk."""
    return _target_version(versions_dir if versions_dir is not None else MIGRATIONS_DIR)


def discover_migrations(versions_dir: Path | None = None) -> list[Migration]:
    """Discover catalog migrations under ``versions_dir`` or the bundled dir."""
    return _discover_migrations(versions_dir if versions_dir is not None else MIGRATIONS_DIR)


def apply_migration(connection: duckdb.DuckDBPyConnection, migration: Migration) -> None:
    """Apply one catalog migration in a transaction."""
    _apply_migration(
        connection,
        migration,
        component=CATALOG_COMPONENT,
        post_apply=_emit_migrate_event,
    )


__all__ = [
    "CATALOG_COMPONENT",
    "MIGRATIONS_DIR",
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
