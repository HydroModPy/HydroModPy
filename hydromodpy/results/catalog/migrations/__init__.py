"""Alembic-like schema migration runner for the catalog DuckDB.

Public API
----------
- :func:`ensure_schema`: bring the connection up to the latest version.
- :func:`current_version`: highest applied version (0 if none).
- :func:`target_version`: highest version on disk.
- :func:`list_migrations`: ordered :class:`Migration` records discovered
  in the ``versions/`` directory.
- :class:`Migration`: Pydantic record for one migration file.
- Errors: :class:`MigrationError`, :class:`SchemaIntegrityError`,
  :class:`MigrationDiscoveryError`, :class:`MigrationExecutionError`.
"""

from hydromodpy.results.catalog.migrations.errors import (
    MigrationDiscoveryError,
    MigrationError,
    MigrationExecutionError,
    SchemaIntegrityError,
)
from hydromodpy.results.catalog.migrations.runner import (
    CATALOG_COMPONENT,
    Migration,
    apply_migration,
    current_version,
    discover_migrations,
    ensure_schema,
    list_migrations,
    target_version,
)

__all__ = [
    "CATALOG_COMPONENT",
    "Migration",
    "MigrationDiscoveryError",
    "MigrationError",
    "MigrationExecutionError",
    "SchemaIntegrityError",
    "apply_migration",
    "current_version",
    "discover_migrations",
    "ensure_schema",
    "list_migrations",
    "target_version",
]
