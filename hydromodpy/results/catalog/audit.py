"""Audit log writer for catalog events.

Hosts a single helper, :func:`emit_audit_event`, which writes one row into
the ``audit_log`` table opened by the catalog DuckDB connection. Callers
emit events at the boundaries of state-changing operations (delete,
purge, ...). The helper resolves the OS user, hostname, and HydroModPy
git commit best-effort; failures fall back to empty strings rather than
breaking the surrounding transaction.

The accepted ``event_type`` values are constrained at the schema level by
the ``CHECK`` on ``audit_log.event_type``; this module mirrors the live
list as a literal type so a typo at the call site fails at type-check
time as well as at SQL-execution time.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import duckdb

logger = get_logger(__name__)

AuditEventType = Literal[
    "sim.register",
    "sim.finalize",
    "sim.delete",
    "sim.purge",
    "sim.rename",
    "sim.tag_add",
    "sim.tag_remove",
    "param.write",
    "param.update",
    "metric.write",
    "tracked_file.add",
    "tracked_file.remove",
    "objective.set",
    "config.replay",
    "migrate",
    "gc",
    "vacuum",
    "export",
    "import",
]

AuditActorKind = Literal["os_user", "principal", "system", "cli", "api"]


def _resolve_actor() -> str:
    try:
        name = os.getlogin()
    except OSError:
        name = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    return name or "unknown"


def _resolve_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def _resolve_git_commit() -> str | None:
    """Return the short HEAD SHA of the HydroModPy install, when present."""
    root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    return out.strip() or None


def _canonical_payload(payload: dict[str, Any] | None) -> str:
    """Deterministic JSON for audit payloads (sorted keys, compact separators)."""
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)


def _fetch_prev_chain_hash(db: duckdb.DuckDBPyConnection) -> str | None:
    """Return the most recent ``chain_hash`` row, or None on cold start."""
    try:
        row = db.execute(
            "SELECT chain_hash FROM audit_log "
            "WHERE chain_hash IS NOT NULL "
            "ORDER BY occurred_at DESC, event_id DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return row[0] if row[0] else None


def _compute_chain_hash(
    *,
    prev_hash: str | None,
    event_id: str,
    event_type: str,
    sim_id: str | None,
    project: str | None,
    payload_json: str,
) -> str:
    """SHA-256 over prev_hash and the immutable subset of the row."""
    parts = [
        prev_hash or "",
        event_id,
        event_type,
        sim_id or "",
        project or "",
        payload_json,
    ]
    blob = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _audit_log_has_chain_columns(db: duckdb.DuckDBPyConnection) -> bool:
    """Detect whether the catalog has been migrated to the hash-chain schema."""
    try:
        row = db.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'audit_log' AND column_name = 'chain_hash'"
        ).fetchone()
    except Exception:
        return False
    return bool(row and int(row[0]) == 1)


def emit_audit_event(
    db: duckdb.DuckDBPyConnection,
    *,
    event_type: AuditEventType,
    actor_kind: AuditActorKind = "os_user",
    sim_id: str | None = None,
    project: str | None = None,
    payload: dict[str, Any] | None = None,
    actor: str | None = None,
    hostname: str | None = None,
    git_commit: str | None = None,
) -> str:
    """Write one event into ``audit_log`` and return the generated ``event_id``.

    The caller controls transactions; the INSERT runs on the supplied
    connection without an enclosing BEGIN/COMMIT so it can be wrapped in
    the same transaction as the operation it audits.

    When the catalog has the hash-chain columns (migration ``0002``), the
    row carries ``prev_hash`` (the chain_hash of the latest row) and
    ``chain_hash`` (SHA-256 over the immutable subset of the new row).
    Cold-start rows have ``prev_hash`` NULL.
    """
    event_id = str(uuid4())
    payload_json = _canonical_payload(payload)
    if _audit_log_has_chain_columns(db):
        prev_hash = _fetch_prev_chain_hash(db)
        chain_hash = _compute_chain_hash(
            prev_hash=prev_hash,
            event_id=event_id,
            event_type=event_type,
            sim_id=sim_id,
            project=project,
            payload_json=payload_json,
        )
        db.execute(
            """INSERT INTO audit_log
                (event_id, actor, actor_kind, event_type, sim_id, project,
                 payload, git_commit, hostname, prev_hash, chain_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id,
                actor if actor is not None else _resolve_actor(),
                actor_kind,
                event_type,
                sim_id,
                project,
                payload_json,
                git_commit if git_commit is not None else _resolve_git_commit(),
                hostname if hostname is not None else _resolve_hostname(),
                prev_hash,
                chain_hash,
            ],
        )
    else:
        db.execute(
            """INSERT INTO audit_log
                (event_id, actor, actor_kind, event_type, sim_id, project,
                 payload, git_commit, hostname)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id,
                actor if actor is not None else _resolve_actor(),
                actor_kind,
                event_type,
                sim_id,
                project,
                payload_json,
                git_commit if git_commit is not None else _resolve_git_commit(),
                hostname if hostname is not None else _resolve_hostname(),
            ],
        )
    return event_id


def verify_chain(db: duckdb.DuckDBPyConnection) -> bool:
    """Recompute and verify the entire ``audit_log`` chain.

    Returns ``True`` when every row whose ``chain_hash`` is set matches the
    recomputed digest of (``prev_hash`` || canonical subset). Rows with a
    NULL ``chain_hash`` are tolerated (pre-migration legacy entries).
    """
    if not _audit_log_has_chain_columns(db):
        return True
    rows = db.execute(
        "SELECT event_id, event_type, sim_id, project, payload, prev_hash, chain_hash "
        "FROM audit_log "
        "WHERE chain_hash IS NOT NULL "
        "ORDER BY occurred_at ASC, event_id ASC"
    ).fetchall()
    expected_prev: str | None = None
    for row in rows:
        event_id, event_type, sim_id, project, payload, prev_hash, chain_hash = row
        sim_id_str = str(sim_id) if sim_id is not None else None
        payload_str = payload if isinstance(payload, str) else (payload or "")
        if isinstance(payload_str, (bytes, bytearray)):
            payload_str = payload_str.decode("utf-8")
        recomputed = _compute_chain_hash(
            prev_hash=prev_hash,
            event_id=str(event_id),
            event_type=str(event_type),
            sim_id=sim_id_str,
            project=str(project) if project is not None else None,
            payload_json=str(payload_str),
        )
        if recomputed != str(chain_hash):
            return False
        if expected_prev is not None and (prev_hash or "") != expected_prev:
            return False
        expected_prev = str(chain_hash)
    return True


def emit_deletion_tombstone(
    db: duckdb.DuckDBPyConnection,
    *,
    sim_id: str,
    sha256_snapshot: str,
    reason: str | None = None,
    deleted_by: str | None = None,
    components: dict[str, Any] | None = None,
) -> None:
    """Insert one GDPR tombstone row into ``deletions``.

    Idempotent on ``sim_id`` (the table's primary key): a re-emission for
    the same sim is treated as a no-op.
    """
    db.execute(
        """INSERT INTO deletions
            (sim_id, deleted_by, reason, components, sha256_snapshot)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (sim_id) DO NOTHING""",
        [
            sim_id,
            deleted_by if deleted_by is not None else _resolve_actor(),
            reason,
            json.dumps(components or {}, sort_keys=True, default=str),
            sha256_snapshot,
        ],
    )


def _coerce_sim_id(value: Any) -> str | None:
    """Normalise a sim_id-shaped value (UUID, str, None) to a string or ``None``."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def audited(
    event_type: AuditEventType,
    *,
    sim_id_arg: str = "sim_id",
    project_arg: str | None = "project",
    payload_keys: tuple[str, ...] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that emits one ``audit_log`` row after the wrapped method succeeds.

    ``sim_id_arg`` and ``project_arg`` name the method arguments whose
    values land in the audit row. ``payload_keys`` selects a subset of
    bound arguments to record in the JSON ``payload`` column. The
    decorator never raises: a logging warning fires if the INSERT fails,
    but the original method's return value is preserved.

    The decorated method must be a bound method on an object that
    exposes ``self._db`` (a DuckDB connection). The audit row is written
    *after* the method returns successfully, so failed mutations are not
    recorded.
    """

    def decorator(method: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(method)

        @functools.wraps(method)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = method(self, *args, **kwargs)
            try:
                bound = signature.bind_partial(self, *args, **kwargs)
                arguments = bound.arguments
                sim_id = _coerce_sim_id(arguments.get(sim_id_arg))
                project: str | None = None
                if project_arg is not None:
                    project_value = arguments.get(project_arg)
                    project = str(project_value) if project_value else None
                payload: dict[str, Any] | None = None
                if payload_keys:
                    payload = {
                        key: arguments[key]
                        for key in payload_keys
                        if key in arguments and arguments[key] is not None
                    }
                emit_audit_event(
                    self._db,
                    event_type=event_type,
                    sim_id=sim_id,
                    project=project,
                    payload=payload,
                )
            except Exception as exc:  # noqa: BLE001 - audit must not raise
                logger.warning("audit emission failed for %s: %s", event_type, exc)
            return result

        return wrapper

    return decorator


__all__ = [
    "AuditActorKind",
    "AuditEventType",
    "audited",
    "emit_audit_event",
    "emit_deletion_tombstone",
    "verify_chain",
]
