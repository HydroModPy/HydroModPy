"""Generic Alembic-like schema migration runner shared by all DuckDB components.

The same runner serves multiple isolated components (catalog, global index,
workspace cache, ...) by parametrizing ``component`` and ``versions_dir`` on
each call.

Public API
----------
- :func:`ensure_schema`: bring a component up to the latest version.
- :func:`current_version`: highest applied version (0 if none).
- :func:`target_version`: highest version on disk.
- :func:`discover_migrations`: ordered :class:`Migration` records.
- :class:`Migration`: Pydantic record for one migration file.
- Errors: :class:`MigrationError`, :class:`SchemaIntegrityError`,
  :class:`MigrationDiscoveryError`, :class:`MigrationExecutionError`.
"""

from hydromodpy.core.migrations.errors import (
    MigrationDiscoveryError,
    MigrationError,
    MigrationExecutionError,
    SchemaIntegrityError,
)
from hydromodpy.core.migrations.runner import (
    DEFAULT_COMPONENT,
    DEFAULT_LOCK_TIMEOUT,
    Migration,
    apply_migration,
    apply_migrations,
    current_version,
    discover_migrations,
    ensure_schema,
    target_version,
)

__all__ = [
    "DEFAULT_COMPONENT",
    "DEFAULT_LOCK_TIMEOUT",
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
