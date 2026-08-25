"""Resume planner driven by the ``workflow_steps`` journal.

The runner asks :class:`ResumePlanner` where it must restart after a crash
or interruption. The planner reads the journal, verifies each completed
step's artefacts still exist with a matching ``outputs_hash``, and returns
a :class:`ResumePlan` that the runner consumes verbatim. Pipeline blueprint
changes or config drift trigger a full restart and cascade-invalidate the
journal rows so a stale completed-prefix never confuses a future resume.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.tracking.journal import WorkflowJournal, WorkflowStepRow

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StepInvalidation:
    """Trace of a single step the planner marked aborted."""

    step_order: int
    step_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """Decision returned by :meth:`ResumePlanner.compute`."""

    run_id: str
    restart_index: int
    last_completed: WorkflowStepRow | None
    invalidated: tuple[StepInvalidation, ...]
    full_restart: bool
    reason: str | None


class ResumePlanner:
    """Decide where the pipeline must restart after a crash or interruption."""

    def __init__(
        self,
        journal: WorkflowJournal,
        workspace: Path,
    ) -> None:
        self._journal = journal
        self._workspace = Path(workspace)

    def compute(
        self,
        *,
        run_id: str,
        current_config_sha256: str | None,
        steps_blueprint: Sequence[str],
    ) -> ResumePlan:
        """Read the journal and return a :class:`ResumePlan` for ``run_id``."""
        rows = self._journal.list_steps(run_id)
        if not rows:
            return ResumePlan(
                run_id=run_id,
                restart_index=0,
                last_completed=None,
                invalidated=(),
                full_restart=False,
                reason="no journal entries",
            )

        blueprint = tuple(steps_blueprint)
        mismatch = _blueprint_mismatch(rows, blueprint)
        if mismatch is not None:
            self._journal.invalidate_from(
                run_id,
                start_order=0,
                reason="blueprint mismatch",
            )
            return ResumePlan(
                run_id=run_id,
                restart_index=0,
                last_completed=None,
                invalidated=tuple(
                    StepInvalidation(r.step_order, r.step_name, "blueprint mismatch") for r in rows
                ),
                full_restart=True,
                reason=mismatch,
            )

        shared = _shared_uris(rows)
        last_done: WorkflowStepRow | None = None
        invalidated: list[StepInvalidation] = []
        expected_order: int | None = None
        for row in rows:
            if expected_order is not None and row.step_order != expected_order:
                break
            if row.status != "completed":
                break
            valid, reason = self._verify_integrity(row, shared=shared)
            if not valid:
                self._journal.invalidate_from(
                    run_id,
                    start_order=row.step_order,
                    reason=reason or "integrity",
                )
                invalidated.append(
                    StepInvalidation(
                        step_order=row.step_order,
                        step_name=row.step_name,
                        reason=reason or "integrity",
                    )
                )
                break
            last_done = row
            expected_order = row.step_order + 1

        restart_index = (last_done.step_order + 1) if last_done is not None else 0
        return ResumePlan(
            run_id=run_id,
            restart_index=restart_index,
            last_completed=last_done,
            invalidated=tuple(invalidated),
            full_restart=False,
            reason=None if not invalidated else invalidated[0].reason,
        )

    def _verify_integrity(
        self,
        row: WorkflowStepRow,
        *,
        shared: frozenset[str],
    ) -> tuple[bool, str | None]:
        """Verify a completed step's artefacts and, when meaningful, its digest.

        ``shared`` holds the URIs several steps of the run write into (the run
        store: ``fields.zarr``, ``tables.parquet``). Those are mutable and
        append-only, so the digest a step recorded at its own end never
        survives the next writer; existence is the only durable signal there.
        A URI owned by a single step still gets its full content check.
        """
        exclusive: list[str] = []
        for uri in row.artifact_uris:
            target = self._workspace / uri
            if not target.exists():
                return False, f"artifact missing: {uri}"
            if uri not in shared:
                exclusive.append(uri)
        if row.outputs_hash is not None and exclusive and len(exclusive) == len(row.artifact_uris):
            recomputed = WorkflowJournal.compute_outputs_hash(
                self._workspace,
                tuple(exclusive),
            )
            if recomputed != row.outputs_hash:
                return False, f"outputs_hash mismatch on step '{row.step_name}'"
        return True, None


def _shared_uris(rows: Sequence[WorkflowStepRow]) -> frozenset[str]:
    """Return the artefact URIs declared by more than one step of the run."""
    seen: set[str] = set()
    shared: set[str] = set()
    for row in rows:
        for uri in row.artifact_uris:
            if uri in seen:
                shared.add(uri)
            else:
                seen.add(uri)
    return frozenset(shared)


def _blueprint_mismatch(
    rows: Sequence[WorkflowStepRow],
    blueprint: Sequence[str],
) -> str | None:
    """Return a human-readable reason when the blueprint diverges from the journal.

    Rows are matched on their ``step_order``, never on their position in the
    result set: a run whose model phase was already built in-process journals
    only its tail, so its first row is not the pipeline's first step.
    """
    if not blueprint:
        return None
    for row in rows:
        order = row.step_order
        if not 0 <= order < len(blueprint):
            return f"step_order {order} outside the current {len(blueprint)}-step pipeline"
        if row.step_name != blueprint[order]:
            return f"step_order {order}: journal={row.step_name!r} blueprint={blueprint[order]!r}"
    return None


__all__ = ("ResumePlan", "ResumePlanner", "StepInvalidation")
