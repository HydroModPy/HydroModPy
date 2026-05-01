"""Pipeline orchestrator.

``Pipeline`` runs a list of :class:`Step` objects sequentially. Between
steps, it records progress in a :class:`StepsLedger` and optionally
persists checkpoints via a :class:`CheckpointStore` so the pipeline can
be resumed after a crash.

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
    from hydromodpy.workflow.internals.ledger import StepsLedger

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
        from hydromodpy.workflow.internals.ledger import StepsLedger
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest

        # Load any third-party solver adapters declared via the
        # ``hydromodpy.solver`` entry-points group. Idempotent: calling this
        # more than once is a no-op (subsequent calls return 0).
        solver_registry.load_plugins()
        solver_registry.load_extractor_plugins()

        ledger = StepsLedger(self.workspace) if self.workspace is not None else None
        cp_store = (
            CheckpointStore(self.workspace, state.run_id)
            if (self.workspace is not None and self.checkpoint_enabled)
            else None
        )

        try:
            start_index = 0 if resume_from is None else int(resume_from)
            manifest: ResolvedRunManifest | None = None
            if self.workspace is not None:
                manifest = ResolvedRunManifest.read(self.workspace, state.run_id)
                if start_index > 0 and manifest is not None:
                    manifest.verify_state(state, self.steps, self.workspace)
                elif start_index == 0:
                    manifest = ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                    manifest.write_atomic(self.workspace)

            if start_index > 0 and cp_store is not None:
                # Restore state from the last successful checkpoint strictly
                # before start_index.
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
                state = self._execute_step(step, state, index, ledger, cp_store)
                if self.workspace is not None:
                    manifest = (
                        ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                        if manifest is None
                        else manifest.with_state(state, self.steps)
                    )
                    manifest.write_atomic(self.workspace)
            return state
        finally:
            if ledger is not None:
                ledger.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_step(
        self,
        step: Step,
        state: PipelineState,
        index: int,
        ledger: StepsLedger | None,
        cp_store: CheckpointStore | None,
    ) -> PipelineState:
        from hydromodpy.workflow.internals.checkpoint import _rebind_unpicklables

        name = getattr(step, "name", step.__class__.__name__)
        state = _rebind_unpicklables(state, self.workspace)
        t0 = time.monotonic()
        if ledger is not None:
            ledger.start(state.run_id, index, name)
        try:
            out = step.run(state)
        except (KeyboardInterrupt, SystemExit):
            # Never swallow user interrupts - let them propagate intact.
            raise
        except StepError as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            if ledger is not None:
                ledger.finish(
                    state.run_id,
                    index,
                    status="failed",
                    elapsed_ms=elapsed_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            if ledger is not None:
                ledger.finish(
                    state.run_id,
                    index,
                    status="failed",
                    elapsed_ms=elapsed_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise StepError(name, exc, run_id=state.run_id) from exc
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        # Normalize step-level metadata even if the step forgot to update.
        out = out.advance(
            step_index=index,
            step_name=name,
            elapsed_ms=elapsed_ms,
            data=out.data,
        )
        if cp_store is not None:
            cp_store.persist(out)
        if ledger is not None:
            ledger.finish(
                state.run_id,
                index,
                status="completed",
                elapsed_ms=elapsed_ms,
            )
        return out


__all__ = ("Pipeline",)
