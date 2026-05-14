"""Pipeline orchestrator.

``Pipeline`` runs a list of :class:`Step` objects sequentially. State is
reconstructed from durable artefacts (Zarr, Parquet, DuckDB rows) plus the
TOML config, never from pickle blobs. The ``workflow_steps`` journal is the
single source of truth for resume decisions: every step records its
``inputs_hash``, ``outputs_hash`` and ``artifact_uris`` rows there. A
:class:`HeartbeatPulse` refreshes ``simulations.last_heartbeat`` while a
step executes so ``hmp gc`` can detect zombie runs.

Two-phase execution
-------------------

``Pipeline.run`` operates in two phases:

* **Rebuild phase** (steps in ``[0, restart_index)``): each step is either
  re-executed in memory (cheap, idempotent steps such as validate, resolve,
  setup) or restored from artefacts via ``Step.rebuild_state`` (heavy steps
  with declared ``artifacts``). No journal rows are written during this
  phase.
* **Execute phase** (steps in ``[restart_index, end)``): each step runs
  fully, the journal records inputs/outputs hashes, and the heartbeat
  thread keeps the sim row fresh.

Resume integrity
----------------

``ResolvedRunManifest`` validates the steps blueprint and the config
SHA-256 before any work starts. The ``ResumePlanner`` then verifies that
every completed step's ``artifact_uris`` still exists and that
``outputs_hash`` matches; on mismatch it cascade-invalidates the journal
rows and forces a full restart. Step failures are wrapped in
:class:`StepError` so callers can react on a typed exception that exposes
``step_name``, ``run_id`` and the original ``cause``. ``KeyboardInterrupt``
and ``SystemExit`` propagate so users can abort via Ctrl+C.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import ResumeIntegrityError, StepError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.internals.step import Step

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.journal import WorkflowJournal

logger = get_logger(__name__)


class Pipeline:
    """Ordered list of steps executed as a single pipeline."""

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        workspace: Path | None = None,
        catalog: SimulationCatalog | None = None,
    ) -> None:
        self.steps: tuple[Step, ...] = tuple(steps)
        self.workspace = Path(workspace) if workspace is not None else None
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
        """Execute steps sequentially.

        ``resume_from`` is the index of the first step to execute fully.
        Steps before that index are reconstructed via ``rebuild_state`` (or
        re-executed in memory when they declare no artefacts).
        """
        from hydromodpy.solver.base import registry as solver_registry
        from hydromodpy.workflow.heartbeat import HeartbeatPulse
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
        from hydromodpy.workflow.journal import WorkflowJournal

        solver_registry.load_plugins()
        solver_registry.load_extractor_plugins()

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

        restart_index = 0 if resume_from is None else int(resume_from)
        restart_index = max(0, min(restart_index, len(self.steps)))

        manifest: ResolvedRunManifest | None = None
        if self.workspace is not None:
            manifest = ResolvedRunManifest.read(self.workspace, state.run_id)
            if restart_index > 0 and manifest is not None:
                manifest.verify_state(state, self.steps, self.workspace)
            elif restart_index == 0:
                manifest = ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                manifest.write_atomic(self.workspace)

        if restart_index == 0 and journal is not None:
            try:
                journal.invalidate_from(state.run_id, start_order=0, reason="from_scratch")
            except Exception as exc:
                logger.debug(
                    "pipeline.journal_invalidate_failed run_id=%s err=%s",
                    state.run_id,
                    exc,
                )

        try:
            state = self._rebuild_prefix(state, restart_index, journal)
            state = self._execute_suffix(
                state,
                restart_index,
                journal=journal,
                manifest=manifest,
                heartbeat_cls=HeartbeatPulse,
            )
        finally:
            if owns_catalog and catalog is not None:
                try:
                    catalog.close()
                except Exception:
                    logger.debug("pipeline.catalog_close_failed", exc_info=True)
        return state

    # ------------------------------------------------------------------
    # Phase 1 - rebuild prior state from artefacts
    # ------------------------------------------------------------------

    def _rebuild_prefix(
        self,
        state: PipelineState,
        restart_index: int,
        journal: WorkflowJournal | None,
    ) -> PipelineState:
        """Reconstruct ``state`` for every step before ``restart_index``."""
        if restart_index <= 0:
            return state

        journal_rows = {}
        if journal is not None and self.workspace is not None:
            try:
                for row in journal.list_steps(state.run_id):
                    journal_rows[row.step_order] = row
            except Exception as exc:
                logger.debug(
                    "pipeline.rebuild_journal_read_failed run_id=%s err=%s",
                    state.run_id,
                    exc,
                )

        for index in range(restart_index):
            step = self.steps[index]
            name = _step_name(step)
            artifacts_method = getattr(step, "artifacts", None)
            declared_artifacts = ()
            if artifacts_method is not None:
                try:
                    declared_artifacts = artifacts_method(state) or ()
                except Exception:
                    declared_artifacts = ()

            row = journal_rows.get(index)
            row_completed = row is not None and row.status == "completed"
            has_artifacts = bool(declared_artifacts) or bool(
                row.artifact_uris if row is not None else ()
            )

            try:
                if has_artifacts and row_completed:
                    rebuild = getattr(step, "rebuild_state", None)
                    if rebuild is not None:
                        state = rebuild(
                            prior_state=state,
                            workspace=self.workspace or Path(),
                            run_id=state.run_id,
                        )
                    else:
                        logger.warning(
                            "pipeline.rebuild_skipped step=%s reason=no_rebuild_state",
                            name,
                        )
                        state = state.advance(step_index=index, step_name=name)
                else:
                    state = step.run(state)
                    state = state.advance(
                        step_index=index,
                        step_name=name,
                        data=state.data,
                    )
            except Exception as exc:
                raise ResumeIntegrityError(
                    f"pipeline rebuild failed at step {index} ({name}): {exc}",
                    run_id=state.run_id,
                ) from exc

        return state

    # ------------------------------------------------------------------
    # Phase 2 - execute remaining steps with journal updates
    # ------------------------------------------------------------------

    def _execute_suffix(
        self,
        state: PipelineState,
        restart_index: int,
        *,
        journal: WorkflowJournal | None,
        manifest: object | None,
        heartbeat_cls: type,
    ) -> PipelineState:
        """Run every step from ``restart_index`` to the end with journal writes."""
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
        from hydromodpy.workflow.journal import WorkflowJournal as _Journal

        if restart_index >= len(self.steps):
            return state

        previous_hashes: list[str] = []
        config_sha256 = _config_sha256_from_manifest(manifest)
        heartbeat_ctx = self._heartbeat_for(journal, state, heartbeat_cls)

        with heartbeat_ctx as pulse:
            _ = pulse  # context only, lifecycle is automatic
            for index in range(restart_index, len(self.steps)):
                step = self.steps[index]
                state = self._execute_step(
                    step,
                    state,
                    index,
                    journal=journal,
                    journal_cls=_Journal,
                    config_sha256=config_sha256,
                    previous_hashes=previous_hashes,
                )
                if self.workspace is not None:
                    manifest = (
                        ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                        if manifest is None
                        else manifest.with_state(state, self.steps)
                    )
                    manifest.write_atomic(self.workspace)
        return state

    def _execute_step(
        self,
        step: Step,
        state: PipelineState,
        index: int,
        *,
        journal: WorkflowJournal | None,
        journal_cls: type,
        config_sha256: str | None,
        previous_hashes: list[str],
    ) -> PipelineState:
        name = _step_name(step)
        inputs_hash = journal_cls.compute_inputs_hash(
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
        artifact_uris = _collect_artifacts(step, out, self.workspace)
        outputs_hash: str | None = None
        if self.workspace is not None:
            outputs_hash = journal_cls.compute_outputs_hash(self.workspace, artifact_uris)
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
            _step_name(step),
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


def _step_name(step: Step) -> str:
    return str(getattr(step, "name", step.__class__.__name__))


__all__ = ("Pipeline",)
