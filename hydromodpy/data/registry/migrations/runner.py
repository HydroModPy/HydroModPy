"""Alembic-like migration runner generic over DuckDB databases.

The runner discovers ``<NNNN>_<slug>.sql`` scripts under ``versions_dir``,
records each application in ``schema_migrations`` and keeps the row of
``_schema_version`` in sync. It is idempotent: rerunning
:func:`ensure_schema` on an up-to-date database applies nothing and only
verifies checksum integrity.

It serves one database, the source-data cache. Its ledger rows carry the
component name ``"data_cache"``, which caches already written hold.

A ledger holding a migration the code does not know means a later version
wrote the database. It is refused before anything runs: this code would write
tables it does not understand. An earlier ledger is what the runner is for.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.filesystem import native_io_path
from hydromodpy.core.logging import get_logger
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.data.registry.migrations.errors import (
    MigrationDiscoveryError,
    MigrationExecutionError,
    SchemaIntegrityError,
)

if TYPE_CHECKING:
    import duckdb

logger = get_logger(__name__)

COMPONENT = "data_cache"
"""The value of the ``component`` column of the ledger of the data cache."""

MIGRATIONS_DIR = Path(__file__).resolve().parent
"""The folder holding the bundled ``<NNNN>_<slug>.sql`` scripts."""

DEFAULT_LOCK_TIMEOUT = 30.0

REPAIR_HINT = (
    "the download cache is a primary record, not an index: restore the newest "
    "'.hmp/backups/cache.duckdb.bak-*' snapshot next to it"
)
"""How to repair a cache whose recorded schema no longer matches the code.

The download cache holds something no rebuild can produce, so its hint is a restore.
"""

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


def current_version(connection: duckdb.DuckDBPyConnection) -> int:
    """Return the highest applied version, 0 if none."""
    if not _has_system_tables(connection):
        return 0
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations WHERE component = ?",
        [COMPONENT],
    ).fetchone()
    return int(row[0]) if row is not None else 0


def target_version(versions_dir: Path = MIGRATIONS_DIR) -> int:
    """Return the highest migration version present on disk."""
    migrations = discover_migrations(versions_dir)
    return migrations[-1].version if migrations else 0


def apply_migration(connection: duckdb.DuckDBPyConnection, migration: Migration) -> None:
    """Apply one migration in a transaction and record it in the ledger."""
    sql = migration.upgrade_sql
    checksum = migration.checksum
    connection.execute("BEGIN TRANSACTION")
    try:
        if sql.strip():
            connection.execute(sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, component, slug, checksum) "
            "VALUES (?, ?, ?, ?)",
            [migration.version, COMPONENT, migration.slug, checksum],
        )
        connection.execute(
            """
            INSERT INTO _schema_version (component, version, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (component) DO UPDATE
                SET version = excluded.version,
                    updated_at = excluded.updated_at
            """,
            [COMPONENT, migration.version],
        )
        connection.execute("COMMIT")
    except Exception as exc:
        connection.execute("ROLLBACK")
        raise MigrationExecutionError(
            f"Failed to apply migration {migration.version:04d}_{migration.slug} "
            f"for the data cache: {exc}. "
            f"To repair, {REPAIR_HINT}."
        ) from exc

    _fold_schema_into_the_database_file(connection, migration)


def _fold_schema_into_the_database_file(
    connection: duckdb.DuckDBPyConnection,
    migration: Migration,
) -> None:
    """Checkpoint so an ``ALTER TABLE`` lives in the database file, not in the journal.

    DuckDB commits into ``<db>.wal`` and only folds it into the database file
    at a clean close. One statement must not be left there: replaying an
    ``ALTER TABLE`` re-binds the table it alters, and on DuckDB 1.5.5 that
    binding raises ``INTERNAL Error: ... Calling
    DatabaseManager::GetDefaultDatabase with no default database set``. The
    replay happens inside ``duckdb.connect``, so the database is then unopenable
    - not by ``hmp``, not by the DuckDB CLI, not read-only - and no repair at
    our layer can reach it. Measured with migration 0003 over the 0001 + 0002
    schema: a process killed by an uncatchable signal at any point of its first
    session left an index nobody could open again, which is every row of the
    workflow journal a resume needs.

    This covers the whole failure mode because the only ``ALTER TABLE`` the
    codebase runs is in a migration script, and ``tests/unit/data/migrations``
    keeps it that way. Views, sequences and indexes replay fine; one added
    outside a migration would need its own checkpoint.

    A checkpoint here costs one page flush per applied migration - a few
    milliseconds, incremental - and only on the session that bootstraps or
    upgrades a database. Rows written afterwards are plain DML and replay
    normally, which is what makes a hard death survivable.
    """
    try:
        connection.execute("CHECKPOINT")
    except Exception as exc:  # noqa: BLE001 - duckdb is a TYPE_CHECKING import here
        logger.warning(
            "Migration %04d_%s is committed but still in the write-ahead "
            "log: %s. Close this database cleanly before killing the process, "
            "a journal holding schema changes cannot be replayed.",
            migration.version,
            migration.slug,
            exc,
        )


def ensure_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path = MIGRATIONS_DIR,
) -> None:
    """Bring the data cache up to the highest available version.

    Creates the two system tables if missing, applies every pending
    migration in order, and verifies checksum integrity for migrations
    already recorded. Safe to call repeatedly.

    Raises :class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`
    when the ledger holds a migration this code does not know.
    """
    _create_system_tables(connection)
    migrations = discover_migrations(versions_dir)
    applied = _load_applied(connection)
    _refuse_a_later_ledger(connection, migrations, applied)

    for migration in migrations:
        recorded = applied.get(migration.version)
        if recorded is None:
            apply_migration(connection, migration)
            continue
        if recorded != migration.checksum:
            raise SchemaIntegrityError(
                f"Checksum mismatch for migration {migration.version:04d}_{migration.slug} "
                f"(data cache): stored {recorded!r}, disk {migration.checksum!r}. "
                f"To repair, {REPAIR_HINT}."
            )


def _refuse_a_later_ledger(
    connection: duckdb.DuckDBPyConnection,
    migrations: list[Migration],
    applied: dict[int, str],
) -> None:
    """Refuse a database whose ledger holds a migration none of *migrations* is."""
    known = {migration.version for migration in migrations}
    unknown = sorted(set(applied) - known)
    if not unknown:
        return
    newest = connection.execute(
        "SELECT version, slug FROM schema_migrations WHERE component = ? "
        "ORDER BY version DESC LIMIT 1",
        [COMPONENT],
    ).fetchone()
    assert newest is not None
    held = f"{int(newest[0]):04d}_{newest[1]}"
    latest = f"{migrations[-1].version:04d}_{migrations[-1].slug}" if migrations else "none"
    raise SchemaVersionMismatchError(
        f"The data cache database holds migration {held}, which HydroModPy "
        f"{HYDROMODPY_VERSION} does not know: its latest is {latest}. A newer version wrote "
        "this database, so upgrade HydroModPy to open it.",
        found=held,
        expected=latest,
    )


def apply_migrations(
    db_path: Path,
    migrations_dir: Path,
    *,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> int:
    """Open ``db_path``, apply pending migrations, return the new version.

    Acquires a :class:`filelock.FileLock` on ``<db_path>.lock`` so concurrent
    callers serialize their migration runs against the same physical database.
    Creates the parent directory of ``db_path`` if missing.
    """
    import duckdb

    db_path = Path(db_path)
    os.makedirs(native_io_path(db_path.parent), exist_ok=True)
    lock = FileLock(native_io_path(f"{db_path}.lock"), timeout=lock_timeout)
    with lock:
        connection = duckdb.connect(str(db_path))
        try:
            ensure_schema(connection, versions_dir=migrations_dir)
            return current_version(connection)
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


def _load_applied(connection: duckdb.DuckDBPyConnection) -> dict[int, str]:
    rows = connection.execute(
        "SELECT version, checksum FROM schema_migrations WHERE component = ?",
        [COMPONENT],
    ).fetchall()
    return {int(version): str(checksum) for version, checksum in rows}
