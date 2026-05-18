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
from hydromodpy.workflow.journal import WorkflowJournal, WorkflowStepRow

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

        last_done: WorkflowStepRow | None = None
        invalidated: list[StepInvalidation] = []
        for row in rows:
            if row.status != "completed":
                break
            valid, reason = self._verify_integrity(row)
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

        restart_index = (last_done.step_order + 1) if last_done is not None else 0
        return ResumePlan(
            run_id=run_id,
            restart_index=restart_index,
            last_completed=last_done,
            invalidated=tuple(invalidated),
            full_restart=False,
            reason=None if not invalidated else invalidated[0].reason,
        )

    def _verify_integrity(self, row: WorkflowStepRow) -> tuple[bool, str | None]:
        """Verify a completed step's artefacts and recomputed digest."""
        for uri in row.artifact_uris:
            target = self._workspace / uri
            if not target.exists():
                return False, f"artifact missing: {uri}"
        if row.outputs_hash is not None and row.artifact_uris:
            recomputed = WorkflowJournal.compute_outputs_hash(
                self._workspace,
                row.artifact_uris,
            )
            if recomputed != row.outputs_hash:
                return False, f"outputs_hash mismatch on step '{row.step_name}'"
        return True, None


def _blueprint_mismatch(
    rows: Sequence[WorkflowStepRow],
    blueprint: Sequence[str],
) -> str | None:
    """Return a human-readable reason when the blueprint diverges from the journal."""
    journal_names = [r.step_name for r in rows]
    limit = min(len(journal_names), len(blueprint))
    for i in range(limit):
        if journal_names[i] != blueprint[i]:
            return f"step_order {i}: journal={journal_names[i]!r} blueprint={blueprint[i]!r}"
    return None


__all__ = ("ResumePlan", "ResumePlanner", "StepInvalidation")
