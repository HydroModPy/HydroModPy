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
import socket
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
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
    "sim.purge.begin",
    "sim.purge.commit",
    "sim.rename",
    "sim.tag_add",
    "sim.tag_remove",
    "sim.trash",
    "sim.restore",
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
    "export.write",
    "import",
    "note.add",
]

AuditActorKind = Literal["os_user", "principal", "system", "cli", "api"]


def _resolve_actor() -> str:
    """Resolve the current actor name through the active ``AuthBackend``.

    Delegates to :func:`hydromodpy.core.auth.get_auth_backend` so every audit
    site shares the same identity source. Failures fall back to the literal
    ``"unknown"`` rather than raising, matching the historical contract that
    audit emission never breaks the surrounding transaction.
    """
    try:
        from hydromodpy.core.auth import get_auth_backend

        return get_auth_backend().current_user() or "unknown"
    except Exception:  # noqa: BLE001 - audit fallback must not raise
        return "unknown"


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


def _canonical_ts(value: Any) -> str:
    """Stable UTC-microsecond string for hashing a TIMESTAMPTZ across the DB round-trip."""
    if value is None:
        return ""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _next_audit_seq(db: duckdb.DuckDBPyConnection) -> int:
    """Return the next monotonic ``seq`` value (``MAX(seq) + 1``).

    Computed inside the caller's transaction; the catalog's single-writer lock
    and the uncommitted-read visibility of the pending insert keep it monotonic
    even for several audit rows written in one transaction.
    """
    row = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_log").fetchone()
    return int(row[0]) if row else 1


def _fetch_prev_chain_hash(db: duckdb.DuckDBPyConnection) -> str | None:
    """Return the ``chain_hash`` of the latest audit row, or None on cold start."""
    row = db.execute(
        "SELECT chain_hash FROM audit_log WHERE chain_hash IS NOT NULL ORDER BY seq DESC LIMIT 1"
    ).fetchone()
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
    occurred_at: Any,
    actor: str | None,
    actor_kind: str | None,
    hostname: str | None,
) -> str:
    """SHA-256 over prev_hash and the tamper-evident subset of the row.

    ``occurred_at``, ``actor``, ``actor_kind`` and ``hostname`` are folded in so
    they cannot be rewritten after the fact without breaking the chain.
    ``occurred_at`` is normalized to a stable UTC-microsecond string so it
    survives the TIMESTAMPTZ round-trip identically on write and on verify.
    """
    parts = [
        prev_hash or "",
        event_id,
        event_type,
        sim_id or "",
        project or "",
        payload_json,
        _canonical_ts(occurred_at),
        actor or "",
        actor_kind or "",
        hostname or "",
    ]
    blob = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


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
    connection without an enclosing BEGIN/COMMIT so it can be wrapped in the
    same transaction as the operation it audits. Each row carries a monotonic
    ``seq``, a ``prev_hash`` (the chain_hash of the latest row, NULL on cold
    start) and a ``chain_hash`` (SHA-256 over the tamper-evident subset of the
    row, including ``occurred_at``/``actor``/``hostname``).
    """
    event_id = str(uuid4())
    payload_json = _canonical_payload(payload)
    occurred_at = datetime.now(UTC)
    actor_value = actor if actor is not None else _resolve_actor()
    hostname_value = hostname if hostname is not None else _resolve_hostname()
    git_commit_value = git_commit if git_commit is not None else _resolve_git_commit()
    prev_hash = _fetch_prev_chain_hash(db)
    chain_hash = _compute_chain_hash(
        prev_hash=prev_hash,
        event_id=event_id,
        event_type=event_type,
        sim_id=sim_id,
        project=project,
        payload_json=payload_json,
        occurred_at=occurred_at,
        actor=actor_value,
        actor_kind=actor_kind,
        hostname=hostname_value,
    )
    db.execute(
        """INSERT INTO audit_log
            (event_id, seq, occurred_at, actor, actor_kind, event_type, sim_id,
             project, payload, git_commit, hostname, prev_hash, chain_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            event_id,
            _next_audit_seq(db),
            occurred_at,
            actor_value,
            actor_kind,
            event_type,
            sim_id,
            project,
            payload_json,
            git_commit_value,
            hostname_value,
            prev_hash,
            chain_hash,
        ],
    )
    return event_id


def verify_chain(db: duckdb.DuckDBPyConnection) -> bool:
    """Recompute and verify the entire ``audit_log`` chain.

    Returns ``True`` when every row whose ``chain_hash`` is set matches the
    recomputed digest of (``prev_hash`` || tamper-evident subset), replayed in
    monotonic ``seq`` order. Rows with a NULL ``chain_hash`` are tolerated.
    """
    rows = db.execute(
        "SELECT event_id, event_type, sim_id, project, payload, prev_hash, chain_hash, "
        "occurred_at, actor, actor_kind, hostname "
        "FROM audit_log WHERE chain_hash IS NOT NULL ORDER BY seq ASC"
    ).fetchall()
    expected_prev: str | None = None
    for row in rows:
        (
            event_id,
            event_type,
            sim_id,
            project,
            payload,
            prev_hash,
            chain_hash,
            occurred_at,
            actor,
            actor_kind,
            hostname,
        ) = row
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
            occurred_at=occurred_at,
            actor=str(actor) if actor is not None else None,
            actor_kind=str(actor_kind) if actor_kind is not None else None,
            hostname=str(hostname) if hostname is not None else None,
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


def apply_retention(
    db: duckdb.DuckDBPyConnection,
    *,
    dry_run: bool = True,
) -> dict[str, int]:
    """Sweep ``audit_log`` against active ``retention_policies``.

    Returns a mapping ``event_type -> rows_deleted_or_eligible``. With
    ``dry_run=True`` (default) the function only counts the rows that
    would be removed; with ``dry_run=False`` it issues DELETE statements
    in a single transaction.

    The table ``retention_policies`` is created by migration ``0003``.
    Catalogs that have not been migrated yet return an empty mapping.
    """
    try:
        policies = db.execute(
            "SELECT event_type, retention_days FROM retention_policies"
        ).fetchall()
    except Exception:
        return {}

    if not policies:
        return {}

    eligible: dict[str, int] = {}
    for event_type, retention_days in policies:
        if retention_days is None:
            continue
        cutoff_days = int(retention_days)
        row = db.execute(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE event_type = ? AND occurred_at < (current_timestamp - INTERVAL '"
            f"{cutoff_days} days')",
            [str(event_type)],
        ).fetchone()
        eligible[str(event_type)] = int(row[0]) if row else 0

    if dry_run:
        return eligible

    db.execute("BEGIN TRANSACTION")
    try:
        for event_type, retention_days in policies:
            if retention_days is None:
                continue
            cutoff_days = int(retention_days)
            db.execute(
                "DELETE FROM audit_log "
                "WHERE event_type = ? AND occurred_at < (current_timestamp - INTERVAL '"
                f"{cutoff_days} days')",
                [str(event_type)],
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return eligible


__all__ = [
    "AuditActorKind",
    "AuditEventType",
    "apply_retention",
    "audited",
    "emit_audit_event",
    "emit_deletion_tombstone",
    "verify_chain",
]
