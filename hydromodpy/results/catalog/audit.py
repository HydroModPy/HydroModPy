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
    "ml.dataset_build",
    "ml.split_persist",
    "ml.scaler_fit",
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
    """
    event_id = str(uuid4())
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
            json.dumps(payload or {}, sort_keys=True, default=str),
            git_commit if git_commit is not None else _resolve_git_commit(),
            hostname if hostname is not None else _resolve_hostname(),
        ],
    )
    return event_id


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
]
