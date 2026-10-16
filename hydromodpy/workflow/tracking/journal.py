"""The step journal of a run: ``<run>/.hmp/checkpoints/steps.json``.

Each pipeline step records a row at start (status ``running``) and the
runner finalises it at end (``completed``, ``failed`` or ``aborted``). The
journal is the source of truth for resume decisions: it stores stable
``inputs_hash`` and ``outputs_hash`` digests and the project-relative
``artifact_uris`` written by the step. It lives with the attempt state of
the run, never in the index: a second attempt in the same directory reads
what the first one left, and the seal of a completed run removes it with
the rest of ``<run>/.hmp/``.

Format
------
One JSON document, ``{"schema": ..., "rows": [...]}``, rewritten atomically
at every change. A row is a :class:`WorkflowStepRow`.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from hydromodpy.core.exceptions import JournalError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import INTERNAL_DIRNAME, RUN_INTERNAL_CHECKPOINTS_DIRNAME
from hydromodpy.results.storage.json_io import read_json, write_json_atomic

logger = get_logger(__name__)

JOURNAL_FILENAME: Final[str] = "steps.json"
"""Name of the journal under ``<run>/.hmp/checkpoints/``."""

JOURNAL_SCHEMA: Final[str] = "hydromodpy.workflow_steps.v1"
"""Schema id of the journal document."""

STEP_STATUSES: Final[frozenset[str]] = frozenset({"running", "completed", "failed", "aborted"})


@dataclass(frozen=True, slots=True)
class WorkflowStepRow:
    """One row of the journal, materialised for the planner."""

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


def journal_path(run_dir: str | Path) -> Path:
    """Return ``<run>/.hmp/checkpoints/steps.json``."""
    return Path(run_dir) / INTERNAL_DIRNAME / RUN_INTERNAL_CHECKPOINTS_DIRNAME / JOURNAL_FILENAME


class WorkflowJournal:
    """The step rows of one run directory, read and rewritten whole."""

    def __init__(self, run_dir: str | Path) -> None:
        self._run_dir = Path(run_dir)

    @property
    def run_dir(self) -> Path:
        """The run directory the journal belongs to."""
        return self._run_dir

    @property
    def path(self) -> Path:
        """Where the journal is written."""
        return journal_path(self._run_dir)

    # -- Writes ------------------------------------------------------------

    def start_step(
        self,
        *,
        run_id: str,
        step_order: int,
        step_name: str,
        inputs_hash: str | None,
    ) -> str:
        """Insert (or replace) the row of ``step_order`` as ``running``; return its id."""
        rows = [r for r in self._rows() if not (r.run_id == run_id and r.step_order == step_order)]
        row = WorkflowStepRow(
            step_id=str(uuid4()),
            run_id=run_id,
            step_order=int(step_order),
            step_name=step_name,
            status="running",
            inputs_hash=inputs_hash,
            outputs_hash=None,
            artifact_uris=(),
            started_at=datetime.now(UTC),
            ended_at=None,
            duration_s=None,
            error_message=None,
        )
        rows.append(row)
        self._write(rows)
        return row.step_id

    def finish_step(
        self,
        *,
        step_id: str,
        status: str,
        outputs_hash: str | None = None,
        artifact_uris: tuple[str, ...] = (),
        error_message: str | None = None,
    ) -> None:
        """Finalise an existing row with its status, duration, digest and artefacts."""
        if status not in STEP_STATUSES or status == "running":
            raise JournalError(f"invalid workflow step status: {status!r}")
        rows = self._rows()
        index = next((i for i, r in enumerate(rows) if r.step_id == step_id), None)
        if index is None:
            raise JournalError(f"unknown workflow step_id: {step_id}")
        row = rows[index]
        ended_at = datetime.now(UTC)
        duration = (
            None
            if row.started_at is None
            else max(0.0, (ended_at - row.started_at).total_seconds())
        )
        rows[index] = WorkflowStepRow(
            step_id=row.step_id,
            run_id=row.run_id,
            step_order=row.step_order,
            step_name=row.step_name,
            status=status,
            inputs_hash=row.inputs_hash,
            outputs_hash=outputs_hash,
            artifact_uris=tuple(artifact_uris),
            started_at=row.started_at,
            ended_at=ended_at,
            duration_s=duration,
            error_message=error_message,
        )
        self._write(rows)

    def invalidate_from(self, run_id: str, *, start_order: int, reason: str) -> int:
        """Mark every row of ``run_id`` at or past ``start_order`` as ``aborted``."""
        rows = self._rows()
        count = 0
        for index, row in enumerate(rows):
            if row.run_id != run_id or row.step_order < int(start_order):
                continue
            rows[index] = WorkflowStepRow(
                **{**asdict(row), "status": "aborted", "error_message": reason}
            )
            count += 1
        if count:
            self._write(rows)
        return count

    # -- Reads -------------------------------------------------------------

    def list_steps(self, run_id: str) -> list[WorkflowStepRow]:
        """Return the rows of ``run_id`` ordered by ``step_order``."""
        return sorted((r for r in self._rows() if r.run_id == run_id), key=lambda r: r.step_order)

    def _rows(self) -> list[WorkflowStepRow]:
        try:
            payload = read_json(self.path)
        except FileNotFoundError:
            return []
        if not isinstance(payload, dict) or payload.get("schema") != JOURNAL_SCHEMA:
            logger.warning("journal.unreadable path=%s: ignored", self.path)
            return []
        return [_row_from_json(item) for item in payload.get("rows", ())]

    def _write(self, rows: list[WorkflowStepRow]) -> None:
        write_json_atomic(
            self.path,
            {"schema": JOURNAL_SCHEMA, "rows": [_row_to_json(row) for row in rows]},
        )

    # -- Hash helpers ------------------------------------------------------

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

        Files are hashed by content. Directories (a Zarr store) are hashed
        recursively over a sorted list of relative file names and their
        bytes. A missing path still contributes its URI so removing an
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


def _row_to_json(row: WorkflowStepRow) -> dict[str, Any]:
    payload = asdict(row)
    payload["artifact_uris"] = list(row.artifact_uris)
    for key in ("started_at", "ended_at"):
        value = payload[key]
        payload[key] = None if value is None else value.isoformat()
    return payload


def _row_from_json(payload: dict[str, Any]) -> WorkflowStepRow:
    return WorkflowStepRow(
        step_id=str(payload["step_id"]),
        run_id=str(payload["run_id"]),
        step_order=int(payload["step_order"]),
        step_name=str(payload["step_name"]),
        status=str(payload["status"]),
        inputs_hash=payload.get("inputs_hash"),
        outputs_hash=payload.get("outputs_hash"),
        artifact_uris=tuple(str(item) for item in payload.get("artifact_uris") or ()),
        started_at=_instant(payload.get("started_at")),
        ended_at=_instant(payload.get("ended_at")),
        duration_s=None if payload.get("duration_s") is None else float(payload["duration_s"]),
        error_message=payload.get("error_message"),
    )


def _instant(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


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
    "JOURNAL_FILENAME",
    "JOURNAL_SCHEMA",
    "WorkflowJournal",
    "WorkflowStepRow",
    "journal_path",
)
