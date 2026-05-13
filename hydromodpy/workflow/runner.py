"""Pipeline orchestrator.

``Pipeline`` runs a list of :class:`Step` objects sequentially. The state of
every step is journaled in the project ``workflow_steps`` table; resume
decisions read that journal instead of the legacy pickle-based
``CheckpointStore``. While a step executes, a :class:`HeartbeatPulse`
refreshes ``simulations.last_heartbeat`` so ``hmp gc`` can detect zombie
runs.

Step failures are wrapped in :class:`StepError` so callers can react on a
typed exception that exposes ``step_name``, ``run_id`` and the original
``cause``. ``KeyboardInterrupt`` and ``SystemExit`` are deliberately not
intercepted: they propagate through the pipeline so users keep their
ability to abort a run via ``Ctrl+C``.

The pickle ``CheckpointStore`` remains available as an opt-in fast-path
for Python rebuilds between steps when ``checkpoint=True``; it now emits
a ``DeprecationWarning`` on first write and will be removed once every
step exposes an ``artifacts()`` view.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import StepError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.internals.step import Step

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.internals.checkpoint import CheckpointStore
    from hydromodpy.workflow.journal import WorkflowJournal

logger = get_logger(__name__)


class Pipeline:
    """Ordered list of steps executed as a single pipeline."""

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        workspace: Path | None = None,
        checkpoint: bool = False,
        catalog: SimulationCatalog | None = None,
    ) -> None:
        self.steps: tuple[Step, ...] = tuple(steps)
        self.workspace = Path(workspace) if workspace is not None else None
        self.checkpoint_enabled = bool(checkpoint)
        self._catalog = catalog

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
        from hydromodpy.workflow.heartbeat import HeartbeatPulse
        from hydromodpy.workflow.internals.checkpoint import CheckpointStore
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
        from hydromodpy.workflow.journal import WorkflowJournal

        solver_registry.load_plugins()
        solver_registry.load_extractor_plugins()

        cp_store = (
            CheckpointStore(self.workspace, state.run_id)
            if (self.workspace is not None and self.checkpoint_enabled)
            else None
        )

        journal: WorkflowJournal | None = None
        catalog = self._catalog
        owns_catalog = False
        if catalog is None and self.workspace is not None:
            try:
                from hydromodpy.results.catalog import SimulationCatalog

                catalog = SimulationCatalog(self.workspace)
                owns_catalog = True
            except Exception as exc:
                logger.debug("pipeline.journal_disabled reason=%s", exc)
                catalog = None
        if catalog is not None:
            journal = WorkflowJournal(catalog)

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

        previous_hashes: list[str] = []
        config_sha256 = _config_sha256_from_manifest(manifest)
        heartbeat_ctx = self._heartbeat_for(journal, state, HeartbeatPulse)

        try:
            with heartbeat_ctx as pulse:
                _ = pulse  # context only, lifecycle is automatic
                for index, step in enumerate(self.steps):
                    if index < start_index:
                        continue
                    state = self._execute_step(
                        step,
                        state,
                        index,
                        cp_store,
                        journal=journal,
                        config_sha256=config_sha256,
                        previous_hashes=previous_hashes,
                    )
                    if self.workspace is not None and self.checkpoint_enabled:
                        manifest = (
                            ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                            if manifest is None
                            else manifest.with_state(state, self.steps)
                        )
                        manifest.write_atomic(self.workspace)
        finally:
            if owns_catalog and catalog is not None:
                try:
                    catalog.close()
                except Exception:
                    logger.debug("pipeline.catalog_close_failed", exc_info=True)
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
        *,
        journal: WorkflowJournal | None,
        config_sha256: str | None,
        previous_hashes: list[str],
    ) -> PipelineState:
        from hydromodpy.workflow.internals.checkpoint import _rebind_unpicklables
        from hydromodpy.workflow.journal import WorkflowJournal as _Journal

        name = getattr(step, "name", step.__class__.__name__)
        state = _rebind_unpicklables(state, self.workspace)

        inputs_hash = _Journal.compute_inputs_hash(
            step_name=name,
            step_order=index,
            config_sha256=config_sha256,
            upstream_outputs_hashes=list(previous_hashes),
        )

        step_id: str | None = None
        if journal is not None:
            try:
                step_id = journal.start_step(
                    run_id=state.run_id,
                    step_order=index,
                    step_name=name,
                    inputs_hash=inputs_hash,
                )
            except Exception as exc:
                logger.warning(
                    "journal.start_step_failed run_id=%s step=%s err=%s",
                    state.run_id,
                    name,
                    exc,
                )

        t0 = time.monotonic()
        try:
            out = step.run(state)
        except (KeyboardInterrupt, SystemExit):
            self._finish_journal_step(
                journal,
                step_id,
                status="aborted",
                outputs_hash=None,
                artifact_uris=(),
                error_message="interrupted",
            )
            raise
        except StepError as exc:
            self._finish_journal_step(
                journal,
                step_id,
                status="failed",
                outputs_hash=None,
                artifact_uris=(),
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            self._finish_journal_step(
                journal,
                step_id,
                status="failed",
                outputs_hash=None,
                artifact_uris=(),
                error_message=f"{type(exc).__name__}: {exc}",
            )
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
        artifact_uris = _collect_artifacts(step, out, self.workspace)
        outputs_hash: str | None = None
        if self.workspace is not None:
            outputs_hash = _Journal.compute_outputs_hash(self.workspace, artifact_uris)
        previous_hashes.append(outputs_hash or "")
        self._finish_journal_step(
            journal,
            step_id,
            status="completed",
            outputs_hash=outputs_hash,
            artifact_uris=artifact_uris,
            error_message=None,
        )
        return out

    @staticmethod
    def _finish_journal_step(
        journal: WorkflowJournal | None,
        step_id: str | None,
        *,
        status: str,
        outputs_hash: str | None,
        artifact_uris: tuple[str, ...],
        error_message: str | None,
    ) -> None:
        if journal is None or step_id is None:
            return
        try:
            journal.finish_step(
                step_id=step_id,
                status=status,
                outputs_hash=outputs_hash,
                artifact_uris=artifact_uris,
                error_message=error_message,
            )
        except Exception as exc:
            logger.warning(
                "journal.finish_step_failed step_id=%s status=%s err=%s",
                step_id,
                status,
                exc,
            )

    def _heartbeat_for(
        self,
        journal: WorkflowJournal | None,
        state: PipelineState,
        heartbeat_cls: type,
    ):
        if journal is None:
            return nullcontext()
        sim_id = _state_sim_id(state)
        if not sim_id:
            return nullcontext()
        return heartbeat_cls(journal, sim_id)


def _collect_artifacts(
    step: Step,
    state_out: PipelineState,
    workspace: Path | None,
) -> tuple[str, ...]:
    """Ask ``step.artifacts(state_out)`` and normalise to workspace-relative POSIX URIs."""
    method = getattr(step, "artifacts", None)
    if method is None:
        return ()
    try:
        raw = method(state_out)
    except Exception as exc:
        logger.debug(
            "step.artifacts_failed name=%s err=%s",
            getattr(step, "name", step.__class__.__name__),
            exc,
        )
        return ()
    if not raw:
        return ()
    normalised: list[str] = []
    for item in raw:
        rel = _to_relative_uri(item, workspace)
        if rel is None:
            continue
        normalised.append(rel)
    return tuple(sorted(set(normalised)))


def _to_relative_uri(item: object, workspace: Path | None) -> str | None:
    """Convert a candidate artefact reference to a workspace-relative URI."""
    if item is None:
        return None
    if isinstance(item, Path):
        path = item
    else:
        path = Path(str(item))
    if workspace is not None and path.is_absolute():
        try:
            return path.relative_to(workspace).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _state_sim_id(state: PipelineState) -> str | None:
    """Return ``sim_id`` carried by the pipeline state if any."""
    data = state.data
    sim_id: object | None = None
    if hasattr(data, "get"):
        try:
            sim_id = data.get("sim_id")  # type: ignore[union-attr]
        except Exception:
            sim_id = None
    if not sim_id:
        ctx = state.get("ctx")
        sim_id = getattr(ctx, "sim_id", None) if ctx is not None else None
    if sim_id in (None, ""):
        return None
    return str(sim_id)


def _config_sha256_from_manifest(manifest: object | None) -> str | None:
    return getattr(manifest, "config_sha256", None) if manifest is not None else None


__all__ = ("Pipeline",)
