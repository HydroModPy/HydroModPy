"""Run-phase orchestration for :class:`hydromodpy.project.Project`.

Holds the run-phase entry points backing the facade: :meth:`ProjectRunner.execute`
runs one attempt of a case through the workflow Pipeline and returns what its
directory says; :meth:`ProjectRunner.run` is the same followed by the index
refresh and the :class:`~hydromodpy.results.run.Run` view ``Project.simulate``
returns; :meth:`ProjectRunner.draft` says what a run would do and runs nothing.
The worker side (``hmp run``) stops at ``execute``: it never opens the index, the
launcher indexes after it.

The attempt protocol (claim of ``runs/<case>/``, pulse, outcome) is
:mod:`hydromodpy.workflow.record.attempt`; the seal is the last step of the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.config_kit.written import log_experimental_keys
from hydromodpy.core.exceptions import ResumeError
from hydromodpy.core.logging import get_logger
from hydromodpy.project.run_overrides import override_changes
from hydromodpy.results.catalog.registration import solve_identity_hash
from hydromodpy.results.storage.attempt import scratch_dir_for_attempt
from hydromodpy.workflow.record.attempt import AttemptHandle, SealedRun, run_attempt, sealed_run_of
from hydromodpy.workflow.record.resume import resolve_resume_step_index
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.window import model_phase_index, step_window

if TYPE_CHECKING:
    from hydromodpy.config.sites.expansion import PlanDraft
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.project.facade import Project
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

DEFAULT_RUN_NAME_TEMPLATE = "run_{counter:04d}"


@contextmanager
def pin_parent_sim_id(ctx: WorkflowContext, parent_sim_id: str | None) -> Iterator[None]:
    """Temporarily set ``ctx.parent_sim_id`` for the duration of the block.

    Restores the previous value on exit, including when an exception
    propagates. ``None`` is a no-op so callers can pass through unchanged.
    """
    if parent_sim_id is None:
        yield
        return
    previous = getattr(ctx, "parent_sim_id", None)
    ctx.parent_sim_id = str(parent_sim_id)
    try:
        yield
    finally:
        ctx.parent_sim_id = previous


def run_view_of(run_dir: Path, *, project_root: Path, sim_id: str) -> Run | None:
    """Return the view of a run directory: a sealed run through its seal, else its store.

    The index lists sealed runs only, so a run that stopped before its seal is read
    through its own store. A run that wrote no facts has nothing to read: ``None``.
    """
    from hydromodpy.results.manifest import is_sealed
    from hydromodpy.results.run.view import Run, open_run_dir
    from hydromodpy.results.storage.run_facts import read_facts
    from hydromodpy.results.storage.run_store import RunStore

    if is_sealed(run_dir):
        return open_run_dir(run_dir)
    if read_facts(run_dir) is None:
        return None
    store = RunStore.open(run_dir, workspace=project_root)
    return Run(sim_id, store)


def _attempt_bracket(
    workspace_path: Path,
    name: str,
    cfg_run: Any,
    config_hash: str | None,
    *,
    fresh: bool,
    force: bool,
):
    """Return the context manager that claims ``runs/<name>/`` and closes its outcome."""
    return run_attempt(
        workspace_path,
        name,
        case_id=name,
        project=workspace_path.name,
        site=getattr(getattr(cfg_run, "site", None), "name", None),
        fresh=fresh,
        force=force,
        config_hash=config_hash,
        if_exists=cfg_run.simulation.if_exists,
    )


def _refuse_resume_of_nothing(handle: AttemptHandle, resume: str, name: str) -> None:
    """Refuse a ``resume`` whose directory holds no interrupted attempt, or say it starts over."""
    claim = handle.claim
    if claim.attempt == 1:
        raise ResumeError(
            f"resume {resume!r}: {handle.run_dir} holds no interrupted attempt to continue."
        )
    # The claim started this attempt over: the previous one ran another
    # configuration, or --fresh was asked. There is nothing to resume.
    logger.info(
        "resume %r: attempt %d of %s starts over from step 0",
        resume,
        claim.attempt,
        handle.run_dir.name if handle.run_dir is not None else name,
    )


@contextmanager
def _frozen_inputs(frozen: bool, workspace_path: Path) -> Iterator[None]:
    """Require frozen input-data references for the block, then restore the previous mode."""
    if not frozen:
        yield
        return
    from hydromodpy.data.provenance.lockfile import frozen_project_root, set_frozen_mode

    previous_root = frozen_project_root()
    set_frozen_mode(True, project_root=workspace_path)
    try:
        yield
    finally:
        set_frozen_mode(previous_root is not None, project_root=previous_root)


class ProjectRunner:
    """Run-phase methods bound to a :class:`Project` instance.

    Composed by :class:`Project` (``project._runner``). Holds no state of
    its own besides the back-reference to ``project``; every call reads or
    mutates the project's workflow context directly.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    # -- High-level workflow entry points ---------------------------------

    def run(
        self,
        *,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        name: str | None = None,
        resume: str | None = None,
        from_step: str | None = None,
        until_step: str | None = None,
        frozen: bool = False,
        no_display: bool = False,
        fresh: bool = False,
        force: bool = False,
        lineage: Any = None,
        calibrated_by: Any = None,
    ) -> Run | None:
        """Run one attempt and return the :class:`Run` view of its directory.

        The index of the project is refreshed from the run directory, but the
        view reads the directory itself: a sealed run through its seal, a run
        that stopped before its seal (``until_step``) through its store. An
        index handle opened earlier in this process keeps the snapshot it
        opened on, so it may not hold the run yet. A run that wrote no
        directory, or no facts to read, returns ``None``.
        """
        sealed = self.execute(
            set=set,
            name=name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            frozen=frozen,
            no_display=no_display,
            fresh=fresh,
            force=force,
            lineage=lineage,
            calibrated_by=calibrated_by,
        )
        if sealed is None:
            return None
        from hydromodpy.project import phases as project_phases
        from hydromodpy.results.catalog.indexer import index_new_runs

        project = self._project
        index_new_runs(sealed.project_root)
        project_phases.open_catalog(project)
        run_view = run_view_of(
            sealed.run_dir, project_root=sealed.project_root, sim_id=sealed.sim_id
        )
        if run_view is not None:
            project._run_history.append(run_view)
        return run_view

    def _run_name(self, name: str | None, resume: str | None) -> str | None:
        """Return the name of a run: asked, or what the configuration calls it."""
        if resume is not None:
            return resume
        if name is not None:
            return name
        # The configuration names its run: ``[simulation] name``, which a TOML file
        # defaults to its own stem.
        return str(getattr(self._project._cfg.simulation, "name", "") or "").strip() or None

    def draft(
        self,
        *,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        name: str | None = None,
        resume: str | None = None,
        from_step: str | None = None,
        until_step: str | None = None,
    ) -> PlanDraft:
        """Say what one run would do, with nothing run and nothing written.

        The draft holds one case: the document of the run with its changes, its
        identity, whether a completed run already holds it, and the steps of its
        window.
        """
        from hydromodpy.config.sites.expansion import single_case_draft
        from hydromodpy.project.dispatch.workflow import completed_identical_run
        from hydromodpy.workflow.steps.sequence import standard_steps

        project = self._project
        all_steps = standard_steps()
        from_idx, until_idx, head_only = step_window(all_steps, from_step, until_step, resume)
        first_model_step = model_phase_index(all_steps)
        start = from_idx
        if start is None and not head_only and self._is_model_phase_ready():
            start = first_model_step
        changes = override_changes(project._cfg, set or {})
        cfg_run = project._cfg.with_changes(changes) if changes else project._cfg
        run_name = self._run_name(name, resume) or DEFAULT_RUN_NAME_TEMPLATE.format(counter=1)
        window = all_steps[start or 0 : None if until_idx is None else until_idx + 1]
        return single_case_draft(
            cfg_run,
            name=run_name,
            config_path=project._config_path,
            steps=tuple(step.name for step in window),
            done=completed_identical_run(cfg_run, name=run_name) is not None,
        )

    def execute(
        self,
        *,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        name: str | None = None,
        resume: str | None = None,
        from_step: str | None = None,
        until_step: str | None = None,
        frozen: bool = False,
        no_display: bool = False,
        fresh: bool = False,
        force: bool = False,
        lineage: Any = None,
        calibrated_by: Any = None,
    ) -> SealedRun | None:
        """Run one attempt of the case through the workflow Pipeline.

        Returns what the run directory says once the attempt is closed, or
        ``None`` for a window that owns no run record. Never opens the index: the
        worker writes its directory, the caller indexes it afterwards.

        ``resume`` names the case to continue; the attempt resumes in place
        from the journal of its directory. ``fresh`` files everything the
        previous attempt left under ``attempts/<k>/`` and starts over.
        ``force`` claims a stale case whose death cannot be proven. ``lineage``
        and ``calibrated_by`` are the blocks a promotion seals its run with.
        """
        from hydromodpy.workflow.steps.sequence import standard_steps

        project = self._project

        # What the launch asks of the figures. It reaches the display step and
        # nothing else: it is no part of the identity or of the sealed config.
        skip_display = bool(project._no_display or project._headless or no_display)

        changes = override_changes(project._cfg, set or {})

        name = self._run_name(name, resume)
        if name is None:
            project._run_counter += 1
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=project._run_counter)

        all_steps = standard_steps()
        steps = all_steps
        from_idx, until_idx, head_only = step_window(all_steps, from_step, until_step, resume)
        if until_idx is not None:
            steps = tuple(all_steps[: until_idx + 1])

        # The Pipeline owns the model phase: it executes ``build_geographic``,
        # ``load_data`` and ``build_mesh`` itself, so each of them gets a
        # journal row and a process death inside one of them leaves a trace.
        workspace_path = self._resolve_workspace_path()
        persisted = bool(project._cfg.simulation.results.persistence.save_catalog)
        claims = not head_only and persisted
        model_phase_ready = not head_only and self._is_model_phase_ready()

        cfg_run = self._load_run_context(name, changes)
        # The lineage belongs to one run: a later point of a sweep starts without it.
        project._ctx.lineage = None
        if lineage is not None and changes:
            lineage = lineage.model_copy(update={"overrides": {**lineage.overrides, **changes}})

        # The identity of this run, computed once: the claim compares it to
        # the one of the previous attempt, the facts of the run record it.
        config_hash = solve_identity_hash(cfg_run) if claims else None
        bracket = (
            _attempt_bracket(workspace_path, name, cfg_run, config_hash, fresh=fresh, force=force)
            if claims
            else nullcontext(None)
        )
        with bracket as handle:
            sim_id = self._execute_attempt(
                handle,
                name=name,
                steps=steps,
                all_steps=all_steps,
                cfg_run=cfg_run,
                workspace_path=workspace_path,
                resume=resume,
                from_idx=from_idx,
                model_phase_ready=model_phase_ready,
                model_phase_index=model_phase_index(all_steps),
                skip_display=skip_display,
                frozen=frozen,
                run_overrides=changes or None,
                config_hash=config_hash,
                lineage=lineage,
                calibrated_by=calibrated_by,
            )
        # The bracket has closed the outcome: what the directory says is final.
        if handle is None or sim_id is None:
            return None
        return sealed_run_of(handle.claim, workspace_path)

    def _load_run_context(self, name: str, changes: Mapping[str, Any]) -> Any:
        """Put the configuration of this run on the context and return it.

        It is the project configuration with the overrides of the run. It is
        what the plan reads, what the Pipeline signs, what the run seals, and
        what every builder reads. ``project._cfg`` stays the configuration the
        project declares; the context carries the one of the run in flight.
        """
        from hydromodpy.workflow.steps.data import rebind_flow_if_stale
        from hydromodpy.workflow.steps.planning import step_build_plan
        from hydromodpy.workflow.steps.setup import rebuild_domain_if_stale

        project = self._project
        cfg_run = project._cfg.with_changes(changes) if changes else project._cfg
        project._ctx.cfg = cfg_run
        # Here and not in the validate step: the prefix of a calibration and its
        # trials run that step too, and a session says it once, at its preflight.
        log_experimental_keys(cfg_run)
        rebuild_domain_if_stale(project._ctx)
        rebind_flow_if_stale(project._ctx)

        step_build_plan(project._ctx, name=name)
        project._ctx.setup.flow_runtime_overrides = None
        project._ctx.setup.run_id = name
        if project._store is not None:
            project._store.close()
            project._store = None
        return cfg_run

    def _execute_attempt(
        self,
        handle: AttemptHandle | None,
        *,
        name: str,
        steps: tuple,
        all_steps: tuple,
        cfg_run: Any,
        workspace_path: Path,
        resume: str | None,
        from_idx: int | None,
        model_phase_ready: bool,
        model_phase_index: int,
        skip_display: bool,
        frozen: bool,
        run_overrides: dict[str, Any] | None,
        config_hash: str | None,
        lineage: Any,
        calibrated_by: Any,
    ) -> str | None:
        """Drive the Pipeline inside the attempt bracket and return the ``sim_id`` of the run."""
        from hydromodpy.workflow.runner import Pipeline

        project = self._project
        run_dir = None if handle is None else handle.run_dir
        resumes = handle is not None and handle.claim.resumed
        if resume is not None and handle is not None and not resumes:
            _refuse_resume_of_nothing(handle, resume, name)
        self._bind_attempt(handle, workspace_path)

        # A model-phase-ready run reuses the model built in this process; its
        # resume_from > 0 is an in-process skip, not a journal resume of a prior
        # attempt (which would otherwise abort on an edited config).
        in_process_skip = False
        if from_idx is not None:
            resume_from: int | None = from_idx
        elif resumes and run_dir is not None:
            resume_from = resolve_resume_step_index(
                run_dir,
                workspace_path,
                name,
                steps_blueprint=tuple(getattr(step, "name", "") for step in all_steps),
            )
        elif model_phase_ready:
            resume_from = model_phase_index
            in_process_skip = True
        else:
            resume_from = None

        initial = self._initial_state(
            name, cfg_run, skip_display, run_overrides, config_hash, run_dir, lineage, calibrated_by
        )

        # A head-only window owns no run record: handing it a directory would
        # let it overwrite the checkpoints of the run that carries this name.
        pipeline = Pipeline(steps, workspace=workspace_path, run_dir=run_dir)
        with _frozen_inputs(frozen, workspace_path):
            final = pipeline.run(
                initial,
                resume_from=resume_from,
                model_phase_ready=in_process_skip,
                heartbeat=None if handle is None else handle.heartbeat,
            )

        if not in_process_skip:
            # The Pipeline built the model phase on the Project's own ctx - a
            # head-only window, a fresh run, or a resume that reconstructed its
            # prefix. The phase marker has to say so or the next call rebuilds
            # what is already there.
            from hydromodpy.project import phases as adopt_phases

            adopt_phases.adopt_pipeline_phase(
                project, tuple(getattr(step, "name", "") for step in steps)
            )

        final_ctx = final.get("ctx") if final is not None else None
        sim_id = getattr(final_ctx, "sim_id", None) if final_ctx is not None else None
        return None if sim_id is None else str(sim_id)

    def _initial_state(
        self,
        name: str,
        cfg_run: Any,
        skip_display: bool,
        run_overrides: dict[str, Any] | None,
        config_hash: str | None,
        run_dir: Path | None,
        lineage: Any,
        calibrated_by: Any,
    ) -> PipelineState:
        """Return the state the Pipeline starts from: the context of the project and this run."""
        project = self._project
        return PipelineState(
            run_id=name,
            data={
                "ctx": project._ctx,
                "cfg": cfg_run,
                "config_path": project._config_path,
                "raw_toml": getattr(project._ctx, "raw_toml", {}) or {},
                "skip_display": skip_display,
                # The geographic preprocessing tree is shared by every run of
                # this Project. Dropping it at the end of the first one leaves
                # the next ones without a DEM to ingest; Project.close() owns it.
                "keep_preprocessing": True,
                "spatial_support_registry": project._spatial_support_registry,
                "requested_spatial_support_ids": project._requested_support_ids,
                "requested_domain_supports": project._requested_domain_supports,
                # This run is already named. ``step_setup`` derives a name from
                # the config when nobody gives it one, which would rename a run
                # the caller named differently.
                "run_name": name,
                # What this run changes on top of the configuration of the project,
                # by dotted path: the lineage of the seal records it.
                "run_overrides": run_overrides,
                "config_hash": config_hash,
                "run_dir": run_dir,
                "lineage": lineage,
                "calibrated_by": calibrated_by,
            },
        )

    def _bind_attempt(self, handle: AttemptHandle | None, workspace_path: Path) -> None:
        """Tell the context which directory and attempt it runs in."""
        ctx = self._project._ctx
        if handle is None:
            ctx.run_dir = None
            return
        claim = handle.claim
        ctx.run_dir = claim.run_dir
        ctx.attempt = claim.attempt
        workspace = ctx.setup.workspace
        if workspace is not None:
            workspace.solver_scratch_folder = scratch_dir_for_attempt(
                workspace_path, claim.run_dir, claim.attempt
            )

    # -- Helpers ----------------------------------------------------------

    def _is_model_phase_ready(self) -> bool:
        """Return True when Project's eager init has produced the runtime objects."""
        setup = self._project._ctx.setup
        return (
            setup.workspace is not None
            and setup.geographic is not None
            and setup.domain is not None
        )

    def _resolve_workspace_path(self) -> Path:
        """Return the project root used for the run directories and checkpoints.

        The runtime workspace only exists once the model phase has been built.
        A run that stops before ``setup_process`` never builds it, so the
        declared ``[workspace] project_root`` answers instead - the loader has
        already made it absolute. The TOML directory stays the last resort.
        """
        project = self._project
        workspace = project._ctx.setup.workspace
        if workspace is not None:
            return Path(workspace.project_root)
        declared_root = getattr(getattr(project._cfg, "workspace", None), "project_root", None)
        if declared_root is not None:
            return Path(declared_root)
        if project._config_path is not None:
            return project._config_path.parent
        return Path.cwd()
