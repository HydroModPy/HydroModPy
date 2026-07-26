"""Pipeline orchestrator.

``Pipeline`` runs a list of :class:`Step` objects sequentially, optionally
folding parallelisable cohorts through a thread pool. State is reconstructed
from durable artefacts (Zarr, Parquet, DuckDB rows) plus the TOML config,
never from pickle blobs. The ``workflow_steps`` journal is the single
source of truth for resume decisions: every step records its
``inputs_hash``, ``outputs_hash`` and ``artifact_uris`` rows there. A
:class:`HeartbeatPulse` emits ``heartbeat`` events on ``workflow_events``
while a step executes so ``hmp catalog gc`` can detect zombie runs.

Two-phase execution
-------------------

``Pipeline.run`` operates in two phases:

* **Rebuild phase** (steps in ``[0, restart_index)``): each step is either
  re-executed in memory (cheap, idempotent steps such as validate, resolve,
  setup) or restored from artefacts via ``Step.rebuild_state`` (heavy steps
  with declared ``artifacts``). No journal rows are written during this
  phase.
* **Execute phase** (steps in ``[restart_index, end)``): cohorts are
  obtained from the Kahn DAG sort; each cohort is dispatched through a
  :class:`ThreadPoolCohortExecutor` (default) or sequentially when the
  caller passes ``parallel=False``. The journal records inputs/outputs
  hashes and the event stream records step_start/step_end markers.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ResumeIntegrityError, StepError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.internals.step import Step

if TYPE_CHECKING:
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.tracking.journal import WorkflowJournal

logger = get_logger(__name__)


class Pipeline:
    """Ordered list of steps executed as a single pipeline."""

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        workspace: Path | None = None,
        catalog: Catalog | None = None,
    ) -> None:
        self.steps: tuple[Step, ...] = tuple(steps)
        self.workspace = Path(workspace) if workspace is not None else None
        self._catalog = catalog
        self._parallel: bool = True

    # ------------------------------------------------------------------
    # DAG helpers
    # ------------------------------------------------------------------

    def dag(self):
        """Return the :class:`WorkflowDAG` view of the declared steps."""
        from hydromodpy.workflow.dag import WorkflowDAG

        return WorkflowDAG(self.steps)

    def cohorts(self) -> tuple[tuple[Step, ...], ...]:
        """Return the Kahn-sorted parallel cohorts of the pipeline."""
        return self.dag().topological_order()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        state: PipelineState,
        *,
        resume_from: int | None = None,
        parallel: bool = True,
        model_phase_ready: bool = False,
    ) -> PipelineState:
        """Execute steps sequentially.

        ``resume_from`` is the index of the first step to execute fully.
        Steps before that index are reconstructed via ``rebuild_state`` (or
        re-executed in memory when they declare no artefacts).

        ``model_phase_ready`` marks a fresh run whose ``resume_from > 0`` only
        skips the model phase already built in this process - not a journal
        resume. Such a run is a new (possibly versioned) run, so it ignores any
        stale same-name manifest and rebuilds its prefix from the live ctx
        rather than a prior run's journalled artefacts. A genuine resume
        (``resume_from > 0`` with this False) keeps verifying the checkpoint.

        ``parallel`` (default True) consumes the Kahn cohort layout: a
        multi-step cohort is dispatched through a thread pool. The
        default 12-step pipeline only produces singleton cohorts so the
        behaviour is identical to the strict for-loop. Pass
        ``parallel=False`` to fall back to the legacy sequential path.
        """
        from hydromodpy.solver.base import registry as solver_registry
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
        from hydromodpy.workflow.tracking.events import WorkflowEventStream
        from hydromodpy.workflow.tracking.heartbeat import HeartbeatPulse
        from hydromodpy.workflow.tracking.journal import WorkflowJournal

        solver_registry.load_plugins()
        solver_registry.load_extractor_plugins()

        self._parallel = bool(parallel)

        journal: WorkflowJournal | None = None
        events: WorkflowEventStream | None = None
        catalog = self._catalog
        owns_catalog = False
        if catalog is None and self.workspace is not None:
            try:
                from hydromodpy.results.catalog import Catalog

                catalog = Catalog(self.workspace)
                owns_catalog = True
            except Exception as exc:
                logger.debug("pipeline.journal_disabled reason=%s", exc)
                catalog = None
        if catalog is not None:
            journal = WorkflowJournal(catalog)
            try:
                events = WorkflowEventStream(catalog)
            except Exception as exc:
                logger.debug("pipeline.events_disabled reason=%s", exc)
                events = None

        restart_index = 0 if resume_from is None else int(resume_from)
        restart_index = max(0, min(restart_index, len(self.steps)))

        manifest: ResolvedRunManifest | None = None
        if self.workspace is not None:
            existing = ResolvedRunManifest.read(self.workspace, state.run_id)
            if restart_index > 0 and not model_phase_ready and existing is not None:
                # Genuine resume: the prefix is reconstructed from the prior
                # run's artefacts, so its config/pipeline must still match.
                existing.verify_state(state, self.steps)
                manifest = existing
            else:
                # Fresh run (restart_index 0) or a model-phase-ready re-run
                # whose config may differ from a stale same-name manifest:
                # write a clean manifest and ignore any prior one.
                manifest = ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                manifest.write_atomic(self.workspace)

        # A from-scratch run and a model-phase-ready re-run rebuild their prefix
        # from the live ctx (is_prebuilt), never from a previous same-name run's
        # journalled artefacts, so drop any stale journal for this run_id.
        if (restart_index == 0 or model_phase_ready) and journal is not None:
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
                events=events,
            )
        finally:
            _close_dangling_store(state)
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
                rebuild = getattr(step, "rebuild_state", None) if row_completed else None
                if rebuild is not None:
                    # The journal says this step already ran to completion, so
                    # restore it from disk whatever it declared: a step that
                    # writes into the shared run store (derive, display) has no
                    # artefact of its own yet must not be executed twice.
                    with progress.phase(name):
                        state = rebuild(
                            prior_state=state,
                            workspace=self.workspace or Path(),
                            run_id=state.run_id,
                        )
                elif has_artifacts and row_completed:
                    logger.warning(
                        "pipeline.rebuild_skipped step=%s reason=no_rebuild_state",
                        name,
                    )
                    state = state.advance(step_index=index, step_name=name)
                else:
                    is_prebuilt = getattr(step, "is_prebuilt", None)
                    if is_prebuilt is not None and is_prebuilt(state):
                        # The in-memory ctx already carries this step's
                        # products (eager facade build); advancing is enough.
                        logger.debug(
                            "pipeline.rebuild_skipped step=%s reason=prebuilt_in_memory",
                            name,
                        )
                        state = state.advance(step_index=index, step_name=name)
                    else:
                        with progress.phase(name):
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
        events: object | None = None,
    ) -> PipelineState:
        """Run every step from ``restart_index`` to the end with journal writes."""
        from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
        from hydromodpy.workflow.parallel import (
            SequentialExecutor,
            ThreadPoolCohortExecutor,
        )
        from hydromodpy.workflow.tracking.journal import WorkflowJournal as _Journal

        if restart_index >= len(self.steps):
            return state

        previous_hashes: list[str] = []
        config_sha256 = _config_sha256_from_manifest(manifest)
        heartbeat_ctx = self._heartbeat_for(state, heartbeat_cls, events=events)

        executor = (
            ThreadPoolCohortExecutor() if getattr(self, "_parallel", True) else SequentialExecutor()
        )
        cohort_layout = self._cohort_layout()

        with heartbeat_ctx as pulse:
            _ = pulse  # context only, lifecycle is automatic
            for cohort_indices in cohort_layout:
                pending = [idx for idx in cohort_indices if idx >= restart_index]
                if not pending:
                    continue
                state = self._execute_cohort(
                    pending,
                    state,
                    executor=executor,
                    journal=journal,
                    journal_cls=_Journal,
                    config_sha256=config_sha256,
                    previous_hashes=previous_hashes,
                    events=events,
                )
                if self.workspace is not None:
                    manifest = (
                        ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                        if manifest is None
                        else manifest.with_state(state, self.steps, self.workspace)
                    )
                    manifest.write_atomic(self.workspace)
        return state

    def _cohort_layout(self) -> tuple[tuple[int, ...], ...]:
        """Return cohort layouts as tuples of step indices.

        Falls back to per-step singletons when (a) the DAG cannot be
        built (cycle, duplicate name) or (b) one or more steps lack an
        explicit ``depends_on`` declaration. The second case preserves
        the legacy linear behaviour for ad-hoc test pipelines whose
        fake steps only define ``name`` and ``run``.
        """
        if not all(callable(getattr(s, "depends_on", None)) for s in self.steps):
            return tuple((idx,) for idx in range(len(self.steps)))
        try:
            cohorts = self.cohorts()
        except Exception as exc:
            logger.debug("pipeline.cohorts_unavailable reason=%s", exc)
            return tuple((idx,) for idx in range(len(self.steps)))
        index_by_id = {id(s): i for i, s in enumerate(self.steps)}
        layout: list[tuple[int, ...]] = []
        for cohort in cohorts:
            entries = [index_by_id[id(s)] for s in cohort if id(s) in index_by_id]
            if entries:
                layout.append(tuple(sorted(entries)))
        if not layout or sum(len(c) for c in layout) != len(self.steps):
            return tuple((idx,) for idx in range(len(self.steps)))
        return tuple(layout)

    def _execute_cohort(
        self,
        cohort_indices: Sequence[int],
        state: PipelineState,
        *,
        executor,
        journal: WorkflowJournal | None,
        journal_cls: type,
        config_sha256: str | None,
        previous_hashes: list[str],
        events: object | None,
    ) -> PipelineState:
        """Execute every step of one cohort and merge their state advances.

        Singleton cohorts behave exactly like the legacy linear path.
        Multi-step cohorts run each step via the executor; their
        resulting ``state.data`` is merged via a last-write-wins union.
        """
        if len(cohort_indices) == 1:
            index = cohort_indices[0]
            return self._execute_step(
                self.steps[index],
                state,
                index,
                journal=journal,
                journal_cls=journal_cls,
                config_sha256=config_sha256,
                previous_hashes=previous_hashes,
                events=events,
            )

        base_state = state

        def _worker(index: int) -> PipelineState:
            scratch_prev: list[str] = list(previous_hashes)
            return self._execute_step(
                self.steps[index],
                base_state,
                index,
                journal=journal,
                journal_cls=journal_cls,
                config_sha256=config_sha256,
                previous_hashes=scratch_prev,
                events=events,
            )

        outcomes = executor.map(_worker, list(cohort_indices))
        merged_data = dict(base_state.data)
        last_index = base_state.step_index
        last_name = base_state.step_name
        last_elapsed = base_state.elapsed_ms
        for outcome in outcomes:
            merged_data.update(outcome.data)
            if outcome.step_index > last_index:
                last_index = outcome.step_index
                last_name = outcome.step_name
                last_elapsed = outcome.elapsed_ms
            if self.workspace is not None:
                step_idx = outcome.step_index
                artifact_uris = _collect_artifacts(self.steps[step_idx], outcome, self.workspace)
                outputs_hash = journal_cls.compute_outputs_hash(self.workspace, artifact_uris)
                previous_hashes.append(outputs_hash or "")
        return base_state.advance(
            step_index=last_index,
            step_name=last_name,
            elapsed_ms=last_elapsed,
            data=merged_data,
        )

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
        events: object | None = None,
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
        if events is not None:
            events.step_start(
                run_id=state.run_id,
                step_name=name,
                step_order=index,
            )

        t0 = time.monotonic()
        try:
            with progress.phase(name):
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
            if events is not None:
                events.step_end(
                    run_id=state.run_id,
                    step_name=name,
                    status="aborted",
                    duration_s=time.monotonic() - t0,
                    error="interrupted",
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
            if events is not None:
                events.step_end(
                    run_id=state.run_id,
                    step_name=name,
                    status="failed",
                    duration_s=time.monotonic() - t0,
                    error=str(exc),
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
            if events is not None:
                events.step_end(
                    run_id=state.run_id,
                    step_name=name,
                    status="failed",
                    duration_s=time.monotonic() - t0,
                    error=f"{type(exc).__name__}: {exc}",
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
        if events is not None:
            events.step_end(
                run_id=state.run_id,
                step_name=name,
                status="completed",
                duration_s=elapsed_ms / 1000.0,
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
        state: PipelineState,
        heartbeat_cls: type,
        *,
        events: object | None = None,
    ):
        if events is None:
            return nullcontext()
        sim_id = _state_sim_id(state)
        if not sim_id:
            return nullcontext()
        return heartbeat_cls(
            sim_id,
            events=events,
            run_id=sim_id,
            step_name="pipeline",
            sidecar_workspace=self.workspace,
        )


def _close_dangling_store(state: PipelineState) -> None:
    """Close the run store when the pipeline stops before the export step.

    ``export`` owns the normal close. A pipeline truncated by ``--until``, or
    one that raised, would otherwise leave the project index open: the DuckDB
    write-ahead log survives the process and the next run has to replay it.
    """
    from hydromodpy.workflow.steps.export import step_close_store

    ctx = state.get("ctx")
    if ctx is None or getattr(ctx, "store", None) is None:
        return
    try:
        step_close_store(ctx)
    except Exception:
        logger.debug("pipeline.store_close_failed", exc_info=True)


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
