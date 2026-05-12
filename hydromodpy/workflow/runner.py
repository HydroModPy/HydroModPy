"""Pipeline orchestrator.

``Pipeline`` runs a list of :class:`Step` objects sequentially. Between
steps, the :class:`CheckpointStore` persists progress so the pipeline can
be resumed after a crash. Pipeline-step bookkeeping (status, elapsed time,
error message) will be unified with the project catalog as the
``workflow_steps`` table once P4 ships the v2 DDL.

Step failures are wrapped in :class:`StepError` (a subclass of
:class:`PipelineError` from ``core.exceptions``) so callers can react on a
typed exception that exposes ``step_name``, ``run_id`` and the original
``cause``. ``KeyboardInterrupt`` and ``SystemExit`` are deliberately not
intercepted: they propagate through the pipeline so users keep their
ability to abort a run via ``Ctrl+C``.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import StepError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.internals.step import Step

if TYPE_CHECKING:
    from hydromodpy.workflow.internals.checkpoint import CheckpointStore

logger = get_logger(__name__)


class Pipeline:
    """Ordered list of steps executed as a single pipeline."""

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        workspace: Path | None = None,
        checkpoint: bool = False,
    ) -> None:
        self.steps: tuple[Step, ...] = tuple(steps)
        self.workspace = Path(workspace) if workspace is not None else None
        self.checkpoint_enabled = bool(checkpoint)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        state: PipelineState,
        *,
        resume_from: int | None = None,
    ) -> PipelineState:
        """Execute steps sequentially from ``resume_from`` (default 0)."""
        from hydromodpy.solver.base import registry as solver_registry
        from hydromodpy.workflow.internals.checkpoint import CheckpointStore
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest

        solver_registry.load_plugins()
        solver_registry.load_extractor_plugins()

        cp_store = (
            CheckpointStore(self.workspace, state.run_id)
            if (self.workspace is not None and self.checkpoint_enabled)
            else None
        )

        start_index = 0 if resume_from is None else int(resume_from)
        manifest: ResolvedRunManifest | None = None
        if self.workspace is not None and self.checkpoint_enabled:
            manifest = ResolvedRunManifest.read(self.workspace, state.run_id)
            if start_index > 0 and manifest is not None:
                manifest.verify_state(state, self.steps, self.workspace)
            elif start_index == 0:
                manifest = ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                manifest.write_atomic(self.workspace)

        if start_index > 0 and cp_store is not None:
            last_saved = cp_store.latest_before(start_index)
            if last_saved is not None:
                state = cp_store.restore(last_saved)
                if manifest is not None:
                    manifest.verify_state(state, self.steps, self.workspace)
                elif self.workspace is not None:
                    manifest = ResolvedRunManifest.from_state(
                        state,
                        self.steps,
                        self.workspace,
                    )
                    manifest.write_atomic(self.workspace)
                logger.info(
                    "pipeline.resume: restored run_id=%s from step %d",
                    state.run_id,
                    last_saved,
                )

        for index, step in enumerate(self.steps):
            if index < start_index:
                continue
            state = self._execute_step(step, state, index, cp_store)
            if self.workspace is not None and self.checkpoint_enabled:
                manifest = (
                    ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                    if manifest is None
                    else manifest.with_state(state, self.steps)
                )
                manifest.write_atomic(self.workspace)
        return state

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_step(
        self,
        step: Step,
        state: PipelineState,
        index: int,
        cp_store: CheckpointStore | None,
    ) -> PipelineState:
        from hydromodpy.workflow.internals.checkpoint import _rebind_unpicklables

        name = getattr(step, "name", step.__class__.__name__)
        state = _rebind_unpicklables(state, self.workspace)
        t0 = time.monotonic()
        try:
            out = step.run(state)
        except (KeyboardInterrupt, SystemExit):
            raise
        except StepError:
            raise
        except Exception as exc:
            raise StepError(name, exc, run_id=state.run_id) from exc
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        out = out.advance(
            step_index=index,
            step_name=name,
            elapsed_ms=elapsed_ms,
            data=out.data,
        )
        if cp_store is not None:
            cp_store.persist(out)
        return out


__all__ = ("Pipeline",)
