"""Machine-wide global index DuckDB schema migrations.

Thin wrapper that binds the generic migration runner from
``hydromodpy.core.migrations`` to the bundled SQL directory and to the
``"index"`` component name.
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
from hydromodpy.core.migrations import list_migrations as _list_migrations
from hydromodpy.core.migrations import target_version as _target_version

if TYPE_CHECKING:
    import duckdb

INDEX_COMPONENT = "index"

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def ensure_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path | None = None,
) -> None:
    """Bring the global index DuckDB schema up to the latest bundled version."""
    _ensure_schema(
        connection,
        versions_dir=versions_dir if versions_dir is not None else _MIGRATIONS_DIR,
        component=INDEX_COMPONENT,
    )


def apply_migrations(db_path: Path, versions_dir: Path | None = None) -> int:
    """Open ``db_path`` and apply pending index migrations."""
    return _apply_migrations(
        db_path,
        versions_dir if versions_dir is not None else _MIGRATIONS_DIR,
        component=INDEX_COMPONENT,
    )


def current_version(connection: duckdb.DuckDBPyConnection) -> int:
    """Return the highest applied index migration version (0 if none)."""
    return _current_version(connection, component=INDEX_COMPONENT)


def target_version(versions_dir: Path | None = None) -> int:
    """Return the highest index migration version present on disk."""
    return _target_version(versions_dir if versions_dir is not None else _MIGRATIONS_DIR)


def discover_migrations(versions_dir: Path | None = None) -> list[Migration]:
    """Discover index migrations under ``versions_dir`` or the bundled dir."""
    return _discover_migrations(versions_dir if versions_dir is not None else _MIGRATIONS_DIR)


def list_migrations(versions_dir: Path | None = None) -> list[Migration]:
    """List index migrations sorted by version."""
    return _list_migrations(versions_dir if versions_dir is not None else _MIGRATIONS_DIR)


def apply_migration(connection: duckdb.DuckDBPyConnection, migration: Migration) -> None:
    """Apply one index migration in a transaction."""
    _apply_migration(connection, migration, component=INDEX_COMPONENT)


__all__ = [
    "INDEX_COMPONENT",
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
    "list_migrations",
    "target_version",
]
