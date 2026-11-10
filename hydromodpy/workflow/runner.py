"""Pipeline orchestrator.

``Pipeline`` runs a list of :class:`Step` objects sequentially, optionally
folding parallelisable cohorts through a thread pool. State is reconstructed
from durable artifacts (Zarr, Parquet, the facts of the run) plus the TOML
config, never from pickle blobs. The step journal under
``<run>/.hmp/checkpoints/`` is the single source of truth for resume
decisions: every step records its ``inputs_hash``, ``outputs_hash`` and
``artifact_uris`` rows there. The pulse of the run is written by the
:class:`~hydromodpy.results.heartbeat.HeartbeatThread` the caller started at
the entry of the process; the pipeline only names the step under way on it.

Two-phase execution
-------------------

``Pipeline.run`` operates in two phases:

* **Rebuild phase** (steps in ``[0, restart_index)``): each step is either
  re-executed in memory (cheap, idempotent steps such as validate, resolve,
  setup) or restored from artifacts via ``Step.rebuild_state`` (heavy steps
  with declared ``artifacts``). No journal rows are written during this
  phase.
* **Execute phase** (steps in ``[restart_index, end)``): cohorts are
  obtained from the Kahn DAG sort; each cohort is dispatched through a
  :class:`ThreadPoolCohortExecutor` (default) or sequentially when the
  caller passes ``parallel=False``. The journal records inputs/outputs
  hashes.

A pipeline without a run directory (a head-only window, a calibration trial)
keeps no journal and no checkpoint: it owns no run record.

Stop and profile
----------------

Before each cohort the pipeline reads the stop flag of the run
(``<run>/.hmp/stop.json``) and raises
:class:`~hydromodpy.core.runtime.interrupts.StopRequested` when it is there, so a
stop asked between two steps ends the run before the next step, the seal included.
A step that was running when the flag was read by the solver ends ``aborted`` in
the journal, and a resume plays it again from its start. Each step is timed by
:func:`~hydromodpy.core.runtime.stopwatch.measured` and its line is added to
``profile.json`` as soon as it ends, so a stopped run keeps the profile of what it
did. A step rebuilt from the artifacts of an earlier attempt is a ``prefix`` line.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import ResumeIntegrityError, StepError, WorkflowDAGCycleError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import raise_if_stop_requested
from hydromodpy.core.runtime.stopwatch import Measure, measured, process_age_s
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.results.storage.run_profile import (
    Profile,
    ProfileLine,
    read_profile,
    write_profile,
)
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.step import Step, step_name

if TYPE_CHECKING:
    from hydromodpy.results.heartbeat import HeartbeatThread
    from hydromodpy.workflow.record.journal import WorkflowJournal
    from hydromodpy.workflow.record.manifest import ResolvedRunManifest

logger = get_logger(__name__)

_PROFILE_LOCK = threading.Lock()
"""Orders the read and the rewrite of ``profile.json`` when the steps of a cohort run in threads."""


def record_measure(
    run_dir: Path | None,
    measure: Measure,
    *,
    attempt: int,
    reused: str = "no",
    key: str | None = None,
) -> None:
    """Add the line of a finished ``measure`` to ``<run>/profile.json``.

    A step, a solve, a figure and an export all come through here. ``reused`` says
    whether the work was done (``no``), rebuilt from an earlier attempt (``prefix``)
    or read from the project store (``store``, with its ``key``). Without a run
    directory there is no profile and nothing is written.
    """
    if run_dir is None:
        return
    line = ProfileLine.of(measure, attempt=attempt, reused=reused, key=key)
    with _PROFILE_LOCK:
        profile = read_profile(run_dir) or Profile()
        write_profile(run_dir, profile.with_line(line))


def _attempt_of(state: PipelineState) -> int:
    """The attempt the context of ``state`` runs in, 1 when it carries none."""
    return int(getattr(state.get("ctx"), "attempt", 1) or 1)


class Pipeline:
    """Ordered list of steps executed as a single pipeline."""

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        workspace: Path | None = None,
        run_dir: Path | None = None,
    ) -> None:
        self.steps: tuple[Step, ...] = tuple(steps)
        self.workspace = Path(workspace) if workspace is not None else None
        self.run_dir = Path(run_dir) if run_dir is not None else None
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
        heartbeat: HeartbeatThread | None = None,
    ) -> PipelineState:
        """Execute steps sequentially.

        ``resume_from`` is the index of the first step to execute fully.
        Steps before that index are reconstructed via ``rebuild_state`` (or
        re-executed in memory when they declare no artifacts).

        ``model_phase_ready`` marks a fresh run whose ``resume_from > 0`` only
        skips the model phase already built in this process - not a journal
        resume. Such a run is a new (possibly versioned) run, so it ignores any
        stale same-name manifest and rebuilds its prefix from the live ctx
        rather than a prior run's journalled artifacts. A genuine resume
        (``resume_from > 0`` with this False) keeps verifying the checkpoint.

        ``parallel`` (default True) consumes the Kahn cohort layout: a
        multi-step cohort is dispatched through a thread pool. The default
        pipeline only produces singleton cohorts so the behavior is identical
        to the strict for-loop. Pass ``parallel=False`` to force the
        sequential path.

        ``heartbeat`` is the pulse of the attempt, started by the caller; the
        pipeline names the step under way on it.
        """
        from hydromodpy.workflow.record.journal import WorkflowJournal

        self._parallel = bool(parallel)

        journal: WorkflowJournal | None = None
        if self.run_dir is not None:
            journal = WorkflowJournal(self.run_dir)

        restart_index = 0 if resume_from is None else int(resume_from)
        restart_index = max(0, min(restart_index, len(self.steps)))

        # A step that leaves a document beside the run checkpoint has to write
        # it where this pipeline owns a run record, and nowhere when it owns
        # none. Reading the project root off the config instead would let a
        # head-only window - which is handed no run directory precisely so it
        # writes no run record - overwrite the documents of the run that
        # carries the same name. A directory the caller already put in the
        # state (a promotion reserves it) is never erased.
        if self.run_dir is not None:
            state = state.with_data(run_dir=self.run_dir)
        manifest = self._open_manifest(state, restart_index, model_phase_ready)
        self._open_profile(state)

        # A from-scratch run and a model-phase-ready re-run rebuild their prefix
        # from the live ctx (is_prebuilt), never from a previous attempt's
        # journalled artifacts, so drop any stale journal for this run_id.
        if (restart_index == 0 or model_phase_ready) and journal is not None:
            journal.invalidate_from(state.run_id, start_order=0, reason="from_scratch")

        config_sha256 = _config_sha256_from_manifest(manifest)
        state, prefix_hashes = self._rebuild_prefix(
            state,
            restart_index,
            journal,
            config_sha256=config_sha256,
        )
        return self._execute_suffix(
            state,
            restart_index,
            journal=journal,
            manifest=manifest,
            heartbeat=heartbeat,
            previous_hashes=prefix_hashes,
        )

    def _open_profile(self, state: PipelineState) -> None:
        """Note the age of the process when this attempt began, in ``profile.json``."""
        if self.run_dir is None:
            return
        with _PROFILE_LOCK:
            profile = read_profile(self.run_dir) or Profile()
            write_profile(self.run_dir, profile.with_start(_attempt_of(state), process_age_s()))

    def _open_manifest(
        self, state: PipelineState, restart_index: int, model_phase_ready: bool
    ) -> ResolvedRunManifest | None:
        """Verify the manifest of a genuine resume, or write a clean one."""
        from hydromodpy.workflow.record.manifest import ResolvedRunManifest

        if self.run_dir is None:
            return None
        existing = ResolvedRunManifest.read(self.run_dir)
        if restart_index > 0 and not model_phase_ready and existing is not None:
            # Genuine resume: the prefix is reconstructed from the prior
            # attempt's artifacts, so its config/pipeline must still match.
            existing.verify_state(state, self.steps, run_dir=self.run_dir)
            return existing
        # Fresh run (restart_index 0) or a model-phase-ready re-run whose config
        # may differ from a stale same-name manifest: write a clean manifest and
        # ignore any prior one.
        manifest = ResolvedRunManifest.from_state(state, self.steps, self.workspace)
        manifest.write_atomic(self.run_dir)
        return manifest

    # ------------------------------------------------------------------
    # Phase 1 - rebuild prior state from artifacts
    # ------------------------------------------------------------------

    def _rebuild_prefix(
        self,
        state: PipelineState,
        restart_index: int,
        journal: WorkflowJournal | None,
        *,
        config_sha256: str | None = None,
    ) -> tuple[PipelineState, list[str]]:
        """Reconstruct ``state`` for every step before ``restart_index``.

        Returns the reconstructed state and the ``outputs_hash`` of each prefix
        step, in order, so the executed suffix chains its ``inputs_hash`` onto
        the same sequence a from-scratch run would have produced.

        A prefix step the journal does not know about gets a row here. The
        model phase of a run driven by the facade is built before the pipeline
        starts and reaches this branch every time: without the row, the journal
        of a finished run describes its tail only, and a later resume has
        nothing to tell it what the head left on disk.
        """
        previous_hashes: list[str] = []
        if restart_index <= 0:
            return state, previous_hashes

        journal_rows = {}
        if journal is not None:
            for row in journal.list_steps(state.run_id):
                journal_rows[row.step_order] = row

        for index in range(restart_index):
            step = self.steps[index]
            row = journal_rows.get(index)
            row_completed = row is not None and row.status == "completed"
            try:
                with measured("step", step_name(step)) as measure:
                    state = self._rebuild_step(step, index, state, row)
            except Exception as exc:
                # Any failure of a step rebuilt from disk is a broken resume, said as one.
                raise ResumeIntegrityError(
                    f"pipeline rebuild failed at step {index} ({step_name(step)}): {exc}",
                    run_id=state.run_id,
                ) from exc

            record_measure(self.run_dir, measure, attempt=_attempt_of(state), reused="prefix")
            previous_hashes.append(
                self._journal_rebuilt_step(
                    step,
                    state,
                    index,
                    journal=journal,
                    keep_existing_row=row_completed,
                    config_sha256=config_sha256,
                    previous_hashes=previous_hashes,
                )
            )

        return state, previous_hashes

    def _rebuild_step(
        self, step: Step, index: int, state: PipelineState, row: Any
    ) -> PipelineState:
        """Bring one prefix step back: restore it from disk, advance past it, or re-run it."""
        name = step_name(step)
        row_completed = row is not None and row.status == "completed"
        if row_completed and getattr(step, "rebuild_state", None) is not None:
            # The journal says this step already ran to completion, so restore
            # it from disk whatever it declared: a step that writes into the
            # shared run store (derive, display) has no artifact of its own yet
            # must not be executed twice.
            with progress.phase(name):
                ctx = state.get("ctx")
                if ctx is not None:
                    ctx.execution.resumed = True
                try:
                    return step.rebuild_state(
                        prior_state=state,
                        workspace=self.workspace or Path(),
                        run_id=state.run_id,
                    )
                finally:
                    if ctx is not None:
                        ctx.execution.resumed = False
        if row_completed and _has_artifacts(step, state, row):
            logger.warning("pipeline.rebuild_skipped step=%s reason=no_rebuild_state", name)
            return state.advance(step_index=index, step_name=name)
        is_prebuilt = getattr(step, "is_prebuilt", None)
        if is_prebuilt is not None and is_prebuilt(state):
            # The in-memory ctx already carries this step's products (eager
            # facade build); advancing is enough.
            logger.debug("pipeline.rebuild_skipped step=%s reason=prebuilt_in_memory", name)
            return state.advance(step_index=index, step_name=name)
        with progress.phase(name):
            state = step.run(state)
        return state.advance(step_index=index, step_name=name, data=state.data)

    def _journal_rebuilt_step(
        self,
        step: Step,
        state_out: PipelineState,
        index: int,
        *,
        journal: WorkflowJournal | None,
        keep_existing_row: bool,
        config_sha256: str | None,
        previous_hashes: Sequence[str],
    ) -> str:
        """Record a reconstructed prefix step and return its ``outputs_hash``.

        A row already marked completed stays: it is the evidence the resume
        planner just verified, and recomputing it here would replace a
        measurement by a re-measurement. Any other row is replaced. A re-run of
        the same name invalidates its whole journal to ``aborted`` before this
        phase, so a surviving ``aborted`` row on a prefix this process has just
        rebuilt would describe a run that never happened, and would send the
        next resume back to step zero.
        """
        from hydromodpy.workflow.record.journal import WorkflowJournal as _Journal

        name = step_name(step)
        artifact_uris = collect_artifacts(step, state_out, self.workspace)
        outputs_hash = ""
        if self.workspace is not None:
            outputs_hash = _Journal.compute_outputs_hash(self.workspace, artifact_uris) or ""

        if journal is None or keep_existing_row:
            return outputs_hash

        inputs_hash = _Journal.compute_inputs_hash(
            step_name=name,
            step_order=index,
            config_sha256=config_sha256,
            upstream_outputs_hashes=list(previous_hashes),
        )
        step_id = journal.start_step(
            run_id=state_out.run_id,
            step_order=index,
            step_name=name,
            inputs_hash=inputs_hash,
        )
        journal.finish_step(
            step_id=step_id,
            status="completed",
            outputs_hash=outputs_hash or None,
            artifact_uris=artifact_uris,
            error_message=None,
        )
        return outputs_hash

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
        heartbeat: HeartbeatThread | None,
        previous_hashes: Sequence[str] = (),
    ) -> PipelineState:
        """Run every step from ``restart_index`` to the end with journal writes."""
        from hydromodpy.workflow.parallel import (
            SequentialExecutor,
            ThreadPoolCohortExecutor,
        )
        from hydromodpy.workflow.record.journal import WorkflowJournal as _Journal
        from hydromodpy.workflow.record.manifest import ResolvedRunManifest

        if restart_index >= len(self.steps):
            return state

        chained_hashes: list[str] = list(previous_hashes)
        config_sha256 = _config_sha256_from_manifest(manifest)
        executor = (
            ThreadPoolCohortExecutor() if getattr(self, "_parallel", True) else SequentialExecutor()
        )
        cohort_layout = self._cohort_layout()
        stop_flag = None if self.run_dir is None else stop_flag_for(self.run_dir)

        for cohort_indices in cohort_layout:
            pending = [idx for idx in cohort_indices if idx >= restart_index]
            if not pending:
                continue
            if heartbeat is not None:
                heartbeat.set_step(step_name(self.steps[pending[0]]))
            raise_if_stop_requested(stop_flag)
            state = self._execute_cohort(
                pending,
                state,
                executor=executor,
                journal=journal,
                journal_cls=_Journal,
                config_sha256=config_sha256,
                previous_hashes=chained_hashes,
            )
            if self.run_dir is not None:
                manifest = (
                    ResolvedRunManifest.from_state(state, self.steps, self.workspace)
                    if manifest is None
                    else manifest.with_state(state, self.steps, self.workspace)
                )
                manifest.write_atomic(self.run_dir)
        return state

    def _cohort_layout(self) -> tuple[tuple[int, ...], ...]:
        """Return cohort layouts as tuples of step indices.

        Falls back to per-step singletons when (a) the DAG cannot be
        built (cycle, duplicate name) or (b) one or more steps lack an
        explicit ``depends_on`` declaration. The second case preserves
        the linear behavior for ad-hoc test pipelines whose fake steps
        only define ``name`` and ``run``.
        """
        if not all(callable(getattr(s, "depends_on", None)) for s in self.steps):
            return tuple((idx,) for idx in range(len(self.steps)))
        try:
            cohorts = self.cohorts()
        except WorkflowDAGCycleError as exc:
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
    ) -> PipelineState:
        """Execute every step of one cohort and merge their state advances.

        Singleton cohorts behave exactly like the linear path. Multi-step
        cohorts run each step via the executor; their resulting
        ``state.data`` is merged via a last-write-wins union.
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
                artifact_uris = collect_artifacts(self.steps[step_idx], outcome, self.workspace)
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
    ) -> PipelineState:
        name = step_name(step)
        inputs_hash = journal_cls.compute_inputs_hash(
            step_name=name,
            step_order=index,
            config_sha256=config_sha256,
            upstream_outputs_hashes=list(previous_hashes),
        )

        step_id: str | None = None
        if journal is not None:
            step_id = journal.start_step(
                run_id=state.run_id,
                step_order=index,
                step_name=name,
                inputs_hash=inputs_hash,
            )

        t0 = time.monotonic()
        measure: Measure | None = None
        try:
            with measured("step", name) as measure, progress.phase(name):
                out = step.run(state)
        except (KeyboardInterrupt, SystemExit):
            self._finish_journal_step(
                journal, step_id, status="aborted", error_message="interrupted"
            )
            raise
        except StepError as exc:
            self._finish_journal_step(journal, step_id, status="failed", error_message=str(exc))
            raise
        except Exception as exc:
            # The journal row must say "failed" whatever the step raised; the error is re-raised named.
            self._finish_journal_step(
                journal,
                step_id,
                status="failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise StepError(name, exc, run_id=state.run_id) from exc
        finally:
            if measure is not None:
                record_measure(self.run_dir, measure, attempt=_attempt_of(state))
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        out = out.advance(
            step_index=index,
            step_name=name,
            elapsed_ms=elapsed_ms,
            data=out.data,
        )
        artifact_uris = collect_artifacts(step, out, self.workspace)
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
        )
        return out

    @staticmethod
    def _finish_journal_step(
        journal: WorkflowJournal | None,
        step_id: str | None,
        *,
        status: str,
        outputs_hash: str | None = None,
        artifact_uris: tuple[str, ...] = (),
        error_message: str | None = None,
    ) -> None:
        if journal is None or step_id is None:
            return
        journal.finish_step(
            step_id=step_id,
            status=status,
            outputs_hash=outputs_hash,
            artifact_uris=artifact_uris,
            error_message=error_message,
        )


def collect_artifacts(
    step: Step, state_out: PipelineState, workspace: Path | None
) -> tuple[str, ...]:
    """Ask ``step.artifacts(state_out)`` and return workspace-relative POSIX URIs, sorted."""
    method = getattr(step, "artifacts", None)
    if method is None:
        return ()
    try:
        raw = method(state_out)
    except Exception as exc:
        # A step that cannot name its artifacts must not fail a run that already succeeded.
        logger.debug("step.artifacts_failed name=%s err=%s", step_name(step), exc)
        return ()
    return tuple(sorted({_relative_uri(item, workspace) for item in raw or () if item is not None}))


def _relative_uri(item: object, workspace: Path | None) -> str:
    """Return *item* as a POSIX path, relative to the workspace when it lies inside."""
    path = item if isinstance(item, Path) else Path(str(item))
    if workspace is not None and path.is_absolute() and path.is_relative_to(workspace):
        return path.relative_to(workspace).as_posix()
    return path.as_posix()


def _has_artifacts(step: Step, state: PipelineState, row: Any) -> bool:
    """Whether the step declares artifacts, or its journal row recorded some."""
    artifacts_method = getattr(step, "artifacts", None)
    declared: Sequence[str] = ()
    if artifacts_method is not None:
        try:
            declared = artifacts_method(state) or ()
        except Exception:
            # A step that cannot name its artifacts declares none; the journal row decides.
            declared = ()
    return bool(declared) or bool(row.artifact_uris if row is not None else ())


def _config_sha256_from_manifest(manifest: object | None) -> str | None:
    return getattr(manifest, "config_sha256", None) if manifest is not None else None


__all__ = ("Pipeline", "record_measure")
