"""Append-only journal over ``workflow_steps`` in the project catalog.

Each pipeline step records a row at start (status ``running``) and the runner
finalises it at end (status ``completed`` / ``failed`` / ``aborted``). The
journal is the source of truth for resume decisions: it stores stable
``inputs_hash`` / ``outputs_hash`` digests and the workspace-relative
``artifact_uris`` written by the step. Live simulations also poke
``simulations.last_heartbeat`` so that ``hmp gc`` can mark zombies failed.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hydromodpy.core.exceptions import JournalError
from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkflowStepRow:
    """One row from ``workflow_steps``, materialised for the planner."""

    step_id: str
    run_id: str
    step_order: int
    step_name: str
    status: str
    inputs_hash: str | None
    outputs_hash: str | None
    artifact_uris: tuple[str, ...]
    started_at: datetime | None
    ended_at: datetime | None
    duration_s: float | None
    error_message: str | None


class WorkflowJournal:
    """Append-only writer for the ``workflow_steps`` table."""

    def __init__(self, catalog: SimulationCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> SimulationCatalog:
        """Underlying catalog facade."""
        return self._catalog

    @with_lock_retry()
    def start_step(
        self,
        *,
        run_id: str,
        step_order: int,
        step_name: str,
        inputs_hash: str | None,
    ) -> str:
        """Insert (or replace) a row with status ``running`` and return its UUID."""
        step_id = str(uuid4())
        started_at = _utcnow()
        db = self._catalog.connection
        db.execute("BEGIN TRANSACTION")
        try:
            existing = db.execute(
                "SELECT step_id FROM workflow_steps WHERE run_id = ? AND step_order = ?",
                [run_id, int(step_order)],
            ).fetchone()
            if existing is not None:
                db.execute(
                    "DELETE FROM workflow_steps WHERE run_id = ? AND step_order = ?",
                    [run_id, int(step_order)],
                )
            db.execute(
                """
                INSERT INTO workflow_steps
                    (step_id, run_id, step_order, step_name, status_id,
                     started_at, ended_at, duration_s,
                     checkpoint_path, inputs_hash, outputs_hash,
                     error_message, artifact_uris)
                VALUES
                    (?, ?, ?, ?, (SELECT id FROM statuses WHERE code = ?),
                     ?, NULL, NULL,
                     NULL, ?, NULL,
                     NULL, NULL)
                """,
                [
                    step_id,
                    run_id,
                    int(step_order),
                    step_name,
                    "running",
                    started_at,
                    inputs_hash,
                ],
            )
            db.execute("COMMIT")
        except Exception:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            raise
        return step_id

    @with_lock_retry()
    def finish_step(
        self,
        *,
        step_id: str,
        status: str,
        outputs_hash: str | None = None,
        artifact_uris: tuple[str, ...] = (),
        error_message: str | None = None,
    ) -> None:
        """Finalise an existing row with status, duration, hash and artefacts."""
        if status not in ("completed", "failed", "aborted", "partial"):
            raise JournalError(f"invalid workflow step status: {status!r}")
        ended_at = _utcnow()
        db = self._catalog.connection
        db.execute("BEGIN TRANSACTION")
        try:
            row = db.execute(
                "SELECT started_at FROM workflow_steps WHERE step_id = ?",
                [step_id],
            ).fetchone()
            if row is None:
                raise JournalError(f"unknown workflow step_id: {step_id}")
            started_at = row[0]
            duration_s: float | None = None
            if isinstance(started_at, datetime):
                duration_s = max(
                    0.0,
                    (ended_at - _as_utc(started_at)).total_seconds(),
                )
            artifact_payload = json.dumps(list(artifact_uris)) if artifact_uris else None
            db.execute(
                """
                UPDATE workflow_steps
                   SET status_id = (SELECT id FROM statuses WHERE code = ?),
                       ended_at = ?,
                       duration_s = ?,
                       outputs_hash = ?,
                       artifact_uris = ?,
                       error_message = ?
                 WHERE step_id = ?
                """,
                [
                    status,
                    ended_at,
                    duration_s,
                    outputs_hash,
                    artifact_payload,
                    error_message,
                    step_id,
                ],
            )
            db.execute("COMMIT")
        except Exception:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            raise

    @with_lock_retry()
    def list_steps(self, run_id: str) -> list[WorkflowStepRow]:
        """Return all rows for ``run_id`` ordered by ``step_order``."""
        db = self._catalog.connection
        rows = db.execute(
            """
            SELECT ws.step_id, ws.run_id, ws.step_order, ws.step_name,
                   st.code AS status,
                   ws.inputs_hash, ws.outputs_hash, ws.artifact_uris,
                   ws.started_at, ws.ended_at, ws.duration_s, ws.error_message
              FROM workflow_steps ws
              JOIN statuses st ON ws.status_id = st.id
             WHERE ws.run_id = ?
          ORDER BY ws.step_order ASC
            """,
            [run_id],
        ).fetchall()
        return [_row_to_dataclass(row) for row in rows]

    @with_lock_retry()
    def invalidate_from(
        self,
        run_id: str,
        *,
        start_order: int,
        reason: str,
    ) -> int:
        """Mark every row at or below ``start_order`` as ``aborted``."""
        db = self._catalog.connection
        result = db.execute(
            """
            UPDATE workflow_steps
               SET status_id = (SELECT id FROM statuses WHERE code = 'aborted'),
                   error_message = ?
             WHERE run_id = ?
               AND step_order >= ?
            """,
            [reason, run_id, int(start_order)],
        )
        count_row = db.execute(
            "SELECT COUNT(*) FROM workflow_steps WHERE run_id = ? AND step_order >= ? "
            "AND status_id = (SELECT id FROM statuses WHERE code = 'aborted')",
            [run_id, int(start_order)],
        ).fetchone()
        _ = result
        return int(count_row[0]) if count_row else 0

    @with_lock_retry()
    def update_heartbeat(self, sim_id: str) -> None:
        """Refresh ``simulations.last_heartbeat`` for ``sim_id``."""
        if not sim_id:
            return
        db = self._catalog.connection
        db.execute(
            "UPDATE simulations SET last_heartbeat = ? WHERE sim_id = ?",
            [_utcnow(), sim_id],
        )

    # ------------------------------------------------------------------
    # Hash helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_inputs_hash(
        step_name: str,
        step_order: int,
        config_sha256: str | None,
        upstream_outputs_hashes: list[str],
    ) -> str:
        """Stable hash combining step identity, config, and upstream outputs."""
        h = hashlib.sha256()
        h.update(step_name.encode("utf-8"))
        h.update(b":")
        h.update(str(int(step_order)).encode("utf-8"))
        h.update(b":")
        h.update((config_sha256 or "").encode("utf-8"))
        for prev in upstream_outputs_hashes:
            h.update(b":")
            h.update((prev or "").encode("utf-8"))
        return h.hexdigest()

    @staticmethod
    def compute_outputs_hash(workspace: Path, artifact_uris: tuple[str, ...]) -> str:
        """Digest of ``artifact_uris`` content under ``workspace``.

        Files are hashed by content (sha256). Directories (e.g. Zarr stores)
        are hashed recursively over a sorted list of relative file names and
        their bytes. Missing paths still contribute their URI so removing an
        artefact changes the digest.
        """
        workspace = Path(workspace)
        h = hashlib.sha256()
        for uri in sorted(artifact_uris):
            h.update(uri.encode("utf-8"))
            h.update(b"\x00")
            target = workspace / uri
            if not target.exists():
                h.update(b"MISSING")
                continue
            if target.is_file():
                _hash_file(target, h)
            elif target.is_dir():
                _hash_directory(target, h)
            h.update(b"\x00")
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_dataclass(row: tuple[Any, ...]) -> WorkflowStepRow:
    (
        step_id,
        run_id,
        step_order,
        step_name,
        status,
        inputs_hash,
        outputs_hash,
        artifact_uris,
        started_at,
        ended_at,
        duration_s,
        error_message,
    ) = row
    return WorkflowStepRow(
        step_id=str(step_id),
        run_id=str(run_id),
        step_order=int(step_order),
        step_name=str(step_name),
        status=str(status),
        inputs_hash=str(inputs_hash) if inputs_hash is not None else None,
        outputs_hash=str(outputs_hash) if outputs_hash is not None else None,
        artifact_uris=_parse_artifact_uris(artifact_uris),
        started_at=_as_utc(started_at) if isinstance(started_at, datetime) else None,
        ended_at=_as_utc(ended_at) if isinstance(ended_at, datetime) else None,
        duration_s=float(duration_s) if duration_s is not None else None,
        error_message=str(error_message) if error_message is not None else None,
    )


def _parse_artifact_uris(payload: Any) -> tuple[str, ...]:
    if payload is None or payload == "":
        return ()
    if isinstance(payload, (list, tuple)):
        return tuple(str(item) for item in payload)
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return ()
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed)
    return ()


def _hash_file(path: Path, h: hashlib._Hash) -> None:
    h.update(b"F")
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)


def _hash_directory(root: Path, h: hashlib._Hash) -> None:
    h.update(b"D")
    entries: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=True):
        base = Path(dirpath)
        for name in filenames:
            entries.append(base / name)
    entries.sort()
    for entry in entries:
        rel = entry.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        try:
            _hash_file(entry, h)
        except OSError:
            h.update(b"UNREADABLE")
        h.update(b"\x00")


__all__ = (
    "WorkflowJournal",
    "WorkflowStepRow",
)
