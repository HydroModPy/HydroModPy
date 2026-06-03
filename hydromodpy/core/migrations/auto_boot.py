"""Robust boot-time migration with backup, FileLock and rolling history.

``ensure_schema_safe`` wraps :func:`hydromodpy.core.migrations.ensure_schema`
with three guarantees that the bare runner does not provide:

- a ``FileLock`` on ``<db>.lock`` so two processes never migrate the same
  DuckDB file simultaneously (the bare ``ensure_schema`` is unlocked).
- an atomic file-level backup ``<db>.bak-<ISO8601Z>`` taken right before
  any migration runs, with automatic restore-on-failure if the schema
  upgrade raises.
- a rolling history of at most ``MAX_BACKUPS`` snapshots per database
  (oldest removed on overflow).

The opt-out ``HMP_AUTO_MIGRATE=0`` raises :class:`AutoMigrationDisabled`
when a pending migration is detected, leaving the on-disk file untouched.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from filelock import FileLock

from hydromodpy.core.logging import get_logger
from hydromodpy.core.migrations.errors import MigrationError
from hydromodpy.core.migrations.runner import (
    DEFAULT_COMPONENT,
    DEFAULT_LOCK_TIMEOUT,
    Migration,
    current_version,
    discover_migrations,
    ensure_schema,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import duckdb

logger = get_logger(__name__)

MAX_BACKUPS = 5
BACKUP_SUFFIX = ".bak-"
_BACKUP_TS_RE = re.compile(r"^(?P<stem>.+)\.bak-(?P<ts>\d{8}T\d{6}Z)$")
_ENV_OPT_OUT = "HMP_AUTO_MIGRATE"


class AutoMigrationDisabled(MigrationError):
    """Raised when ``HMP_AUTO_MIGRATE=0`` blocks a needed schema upgrade."""


def _is_disabled() -> bool:
    raw = os.environ.get(_ENV_OPT_OUT)
    if raw is None:
        return False
    return raw.strip().lower() in {"0", "false", "no", "off"}


def _format_timestamp() -> str:
    """ISO 8601 UTC stamp safe for filesystem suffixes (``YYYYMMDDThhmmssZ``)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _backup_dir(db_path: Path) -> Path:
    """Hidden directory holding rolling backups next to ``db_path``."""
    return db_path.parent / ".hmp" / "backups"


def backup_path_for(db_path: Path, *, timestamp: str | None = None) -> Path:
    """Return the canonical backup path for ``db_path`` at ``timestamp``.

    Backups live in a hidden ``.hmp/backups/`` folder next to the database so
    they never clutter the project directory.
    """
    stamp = timestamp or _format_timestamp()
    return _backup_dir(db_path) / f"{db_path.name}{BACKUP_SUFFIX}{stamp}"


def list_backups(db_path: Path) -> list[Path]:
    """Return existing backups for ``db_path`` ordered oldest -> newest."""
    backup_dir = _backup_dir(db_path)
    if not backup_dir.is_dir():
        return []
    matches: list[tuple[str, Path]] = []
    for candidate in backup_dir.iterdir():
        m = _BACKUP_TS_RE.match(candidate.name)
        if m is None:
            continue
        if m.group("stem") != db_path.name:
            continue
        matches.append((m.group("ts"), candidate))
    matches.sort(key=lambda item: item[0])
    return [path for _ts, path in matches]


def _prune_old_backups(db_path: Path, *, keep: int = MAX_BACKUPS) -> None:
    """Drop the oldest backups so at most ``keep`` snapshots remain."""
    backups = list_backups(db_path)
    overflow = len(backups) - keep
    if overflow <= 0:
        return
    for stale in backups[:overflow]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("Could not prune stale backup %s: %s", stale, exc)


def _sql_string(value: Path) -> str:
    """Return ``value`` as a single-quoted DuckDB string literal."""
    return "'" + value.as_posix().replace("'", "''") + "'"


def _copy_backup_from_connection(
    connection: duckdb.DuckDBPyConnection,
    backup: Path,
) -> None:
    """Duplicate an open DuckDB database into ``backup``."""
    if backup.exists():
        backup.unlink()
    with TemporaryDirectory(prefix="hmp_duckdb_backup_") as export_root:
        export_dir = Path(export_root)
        connection.execute(f"EXPORT DATABASE {_sql_string(export_dir)}")

        import duckdb as duckdb_module

        backup_connection = duckdb_module.connect(str(backup))
        try:
            backup_connection.execute(f"IMPORT DATABASE {_sql_string(export_dir)}")
            backup_connection.execute("CHECKPOINT")
        finally:
            backup_connection.close()


def _copy_backup(
    db_path: Path,
    backup: Path,
    *,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Atomically duplicate ``db_path`` to ``backup``."""
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(db_path, backup)
    except PermissionError:
        if connection is None:
            raise
        _copy_backup_from_connection(connection, backup)


def restore_backup(db_path: Path, backup: Path) -> None:
    """Restore ``db_path`` from ``backup`` overwriting the current file.

    Raises ``FileNotFoundError`` when the backup is gone. The restore is a
    file-level copy: callers are expected to have released the DuckDB
    connection first.
    """
    if not backup.is_file():
        raise FileNotFoundError(f"Backup file not found: {backup}")
    if db_path.exists():
        db_path.unlink()
    shutil.copy2(backup, db_path)


def _has_pending_migrations(
    connection: duckdb.DuckDBPyConnection,
    *,
    versions_dir: Path,
    component: str,
) -> bool:
    """Return True when the on-disk migration set has more versions than recorded."""
    migrations = discover_migrations(versions_dir)
    if not migrations:
        return False
    latest_on_disk = migrations[-1].version
    applied = current_version(connection, component=component)
    return applied < latest_on_disk


def ensure_schema_safe(
    connection: duckdb.DuckDBPyConnection,
    *,
    db_path: Path,
    versions_dir: Path,
    component: str = DEFAULT_COMPONENT,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    post_apply: Callable[[duckdb.DuckDBPyConnection, Migration, str], None] | None = None,
    allow_auto: bool = True,
) -> None:
    """Bring ``component`` up to the latest version with backup + lock.

    Behaviour:

    - acquires a :class:`filelock.FileLock` on ``<db_path>.lock`` so concurrent
      processes serialise their migrations against the same file.
    - when migrations are pending and ``db_path`` is non-empty, writes a
      backup ``<db_path>.bak-<ISO8601Z>`` first, then calls
      :func:`ensure_schema`.
    - on success prunes old backups so at most :data:`MAX_BACKUPS` remain.
    - on failure restores the backup (file-level copy) and re-raises.
    - when ``HMP_AUTO_MIGRATE=0`` (and ``allow_auto`` is True), pending
      migrations raise :class:`AutoMigrationDisabled` instead of running.
    """
    lock = FileLock(f"{db_path}.lock", timeout=lock_timeout)
    with lock:
        pending = _has_pending_migrations(
            connection,
            versions_dir=versions_dir,
            component=component,
        )
        if not pending:
            ensure_schema(
                connection,
                versions_dir=versions_dir,
                component=component,
                post_apply=post_apply,
            )
            return

        if allow_auto and _is_disabled():
            raise AutoMigrationDisabled(
                f"HMP_AUTO_MIGRATE=0 blocks pending migrations for component "
                f"{component!r} at {db_path}; run 'hmp doctor' or unset the "
                f"variable to migrate."
            )

        backup: Path | None = None
        if db_path.is_file():
            backup = backup_path_for(db_path)
            _copy_backup(db_path, backup, connection=connection)
            logger.debug("Pre-migration backup written: %s", backup)

        try:
            ensure_schema(
                connection,
                versions_dir=versions_dir,
                component=component,
                post_apply=post_apply,
            )
        except Exception:
            if backup is not None and backup.is_file():
                try:
                    connection.close()
                except Exception:
                    pass
                try:
                    restore_backup(db_path, backup)
                    logger.warning("Migration failed; restored backup %s", backup)
                except Exception as restore_exc:  # noqa: BLE001
                    logger.error(
                        "Migration failed and backup restore also failed: %s",
                        restore_exc,
                    )
            raise

        if backup is not None:
            _prune_old_backups(db_path, keep=MAX_BACKUPS)


__all__ = [
    "AutoMigrationDisabled",
    "BACKUP_SUFFIX",
    "MAX_BACKUPS",
    "backup_path_for",
    "ensure_schema_safe",
    "list_backups",
    "restore_backup",
]
