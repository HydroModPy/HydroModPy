"""Run-phase orchestration for :class:`hydromodpy.project.Project`.

Holds the run-phase entry points backing the facade: :meth:`ProjectRunner.execute`
runs one attempt of a case through the workflow Pipeline and returns what its
directory says; :meth:`ProjectRunner.run` is the same followed by the index
refresh and the :class:`~hydromodpy.results.run.Run` view ``Project.simulate``
returns. The worker side (``hmp run``) stops at ``execute``: it never opens
the index, the launcher indexes after it.

The attempt protocol (claim of ``runs/<case>/``, pulse, outcome) is
:mod:`hydromodpy.project.attempt`; the seal is the last step of the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError, ResumeError
from hydromodpy.core.logging import get_logger
from hydromodpy.project.attempt import AttemptHandle, SealedRun, run_attempt, sealed_run_of
from hydromodpy.results.catalog.registration import input_file_digests, run_identity_hash
from hydromodpy.results.storage.attempt import scratch_dir_for_attempt

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.project.facade import Project
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

DEFAULT_RUN_NAME_TEMPLATE = "run_{counter:04d}"


@contextmanager
def _pin_parent_sim_id(ctx: WorkflowContext, parent_sim_id: str | None) -> Iterator[None]:
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


def _resolve_step_index(step: str | int, steps: tuple) -> int:
    """Resolve a step name (or integer/digit string) to a tuple index.

    Accepts either the ``step.name`` attribute (snake_case, e.g.
    ``"setup_process"``), the class name (``"SetupProcessStep"``), the
    class-name prefix (``"setupprocess"``), or a numeric index.
    """
    if isinstance(step, int):
        return step
    text = str(step)
    if text.isdigit():
        return int(text)
    lower = text.lower()
    target = lower.removesuffix("step").rstrip("_")
    flat = target.replace("_", "")
    for idx, obj in enumerate(steps):
        if getattr(obj, "name", None) == lower:
            return idx
        candidate = type(obj).__name__.lower().removesuffix("step").rstrip("_")
        if candidate == flat:
            return idx
    known = ", ".join(type(s).__name__ for s in steps)
    raise ConfigError(f"Unknown pipeline step: {step!r}. Known steps: {known}")


def _bounded_step_index(
    step: str | int | None,
    steps: tuple,
    *,
    label: str,
) -> int | None:
    """Resolve a step bound and refuse one that lands outside the pipeline.

    An index past either end used to run a truncated or empty window and
    report success, which is indistinguishable from a run that did its work.
    """
    if step is None:
        return None
    index = _resolve_step_index(step, steps)
    if not 0 <= index < len(steps):
        raise ConfigError(
            f"{label} {step!r} resolves to index {index}, outside the {len(steps)}-step "
            f"pipeline. Name a step or give an index in 0..{len(steps) - 1}."
        )
    return index


def _model_phase_index(steps: tuple) -> int:
    """Return the index of the first step that consumes the shared model phase.

    ``0`` when the pipeline declares no ``setup_process``: an ad-hoc step list
    makes no claim about a model phase, so every window is treated as needing
    one, which is what the canonical pipeline did before the bound existed.
    """
    for index, step in enumerate(steps):
        if getattr(step, "name", None) == "setup_process":
            return index
    return 0


def scratch_of_resumed_run(project_root: Path, run_name: str) -> str | None:
    """Return the scratch folder the completed steps of ``run_name`` journalled, or None.

    A run journals its preprocessing under the project folder
    ``.hmp/scratch/<run>.p<pid>/``. The resume works in that folder again, or
    the sweep of killed runs would delete what the resume is meant to reuse.
    The journal is read from the run directory (``runs/<name>``, the latest
    version for a bare name), never from the index.
    """
    from hydromodpy.core.state.paths import run_scratch_of
    from hydromodpy.results.storage.attempt import run_dir_for_name
    from hydromodpy.workflow.tracking.journal import WorkflowJournal

    run_dir = run_dir_for_name(Path(project_root), run_name)
    if run_dir is None:
        return None
    rows = WorkflowJournal(run_dir).list_steps(run_name)
    completed = sorted(
        (row for row in rows if row.status == "completed"), key=lambda row: row.step_order
    )
    return run_scratch_of(uri for row in completed for uri in row.artifact_uris)


def _resolve_resume_step_index(
    run_dir: Path,
    workspace: Path,
    run_id: str,
    *,
    steps_blueprint: tuple[str, ...] | None = None,
) -> int:
    """Locate the next step index to execute for a previously interrupted run.

    The step journal under ``<run>/.hmp/checkpoints/`` is the single source of
    truth: when no row exists for ``run_id`` the run is treated as fresh and
    starts from step 0.
    """
    from hydromodpy.workflow.tracking.journal import WorkflowJournal
    from hydromodpy.workflow.tracking.resume import ResumePlanner

    planner = ResumePlanner(WorkflowJournal(run_dir), workspace)
    plan = planner.compute(
        run_id=run_id,
        current_config_sha256=None,
        steps_blueprint=steps_blueprint or (),
    )

    # Make a degraded resume visible: a snapshot-rebuilt config or a changed
    # pipeline can force a full restart, which otherwise looks like a normal run.
    if plan.full_restart:
        logger.warning(
            "resume %r cannot pick up where it left off (%s); restarting from step 0",
            run_id,
            plan.reason or "pipeline or config changed",
        )
    elif plan.restart_index == 0:
        logger.warning(
            "resume %r found no resumable journal (%s); starting fresh from step 0",
            run_id,
            plan.reason or "no journal entries",
        )
    else:
        logger.info(
            "resume %r picks up from step %d (last completed: %s)",
            run_id,
            plan.restart_index,
            plan.last_completed.step_name if plan.last_completed is not None else "?",
        )
    return plan.restart_index


def _print_dry_run_plan(
    *,
    run_id: str,
    steps: tuple,
    resume_from: int | None,
) -> None:
    """Emit the resolved Pipeline plan without executing any step."""
    print(f"[dry-run] run_id    : {run_id}")
    if resume_from is not None:
        print(f"[dry-run] resume_from: {resume_from}")
    print("[dry-run] steps     :")
    for idx, step in enumerate(steps):
        print(f"  {idx:02d}  {type(step).__name__}")


def _identity_overrides(
    overrides: dict[str, Any],
    *,
    first_clim: str | None,
    properties: Any,
) -> dict[str, Any] | None:
    """Return the overrides of one run as the identity hash reads them, or None.

    ``thickness`` is not here: it is folded into the run configuration itself.
    """
    payload: dict[str, Any] = dict(overrides or {})
    if first_clim is not None:
        payload["first_clim"] = first_clim
    if properties is not None:
        payload["properties"] = properties
    return payload or None


def _unsealed_run_view(sealed: SealedRun) -> Run | None:
    """Return the view of a run that stopped before its seal, read from its directory.

    The index lists sealed runs only, so a partial run is read through its
    own store. A run that wrote no facts has nothing to read: ``None``.
    """
    from hydromodpy.results.run.view import Run
    from hydromodpy.results.storage.run_facts import read_facts
    from hydromodpy.results.storage.run_store import RunStore

    if read_facts(sealed.run_dir) is None:
        return None
    store = RunStore.open(sealed.run_dir, workspace=sealed.project_root)
    return Run(sealed.sim_id, store)


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
        name: str | None = None,
        resume: str | None = None,
        from_step: str | int | None = None,
        until_step: str | int | None = None,
        dry_run: bool = False,
        frozen: bool = False,
        no_display: bool = False,
        parallel: bool = True,
        fresh: bool = False,
        force: bool = False,
        lineage: Any = None,
        calibrated_by: Any = None,
        **overrides,
    ) -> Run | None:
        """Run one attempt and return the :class:`Run` view of its directory.

        The index of the project is refreshed from the run directory first,
        so the view of a sealed run answers through it. A run that stopped
        before its seal (``until_step``) is not in the index: its view reads
        the run directory itself. A run that wrote no directory, or no facts
        to read, returns ``None``.
        """
        sealed = self.execute(
            name=name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            dry_run=dry_run,
            frozen=frozen,
            no_display=no_display,
            parallel=parallel,
            fresh=fresh,
            force=force,
            lineage=lineage,
            calibrated_by=calibrated_by,
            **overrides,
        )
        if sealed is None:
            return None
        from hydromodpy.project import phases as project_phases
        from hydromodpy.results.catalog.indexer import index_new_runs
        from hydromodpy.results.manifest import is_sealed

        project = self._project
        index_new_runs(sealed.project_root)
        project_phases.open_catalog(project)
        if is_sealed(sealed.run_dir):
            if project._store is None:
                return None
            run_view = project._store[sealed.sim_id]
        else:
            run_view = _unsealed_run_view(sealed)
            if run_view is None:
                return None
        project._run_history.append(run_view)
        return run_view

    def execute(
        self,
        *,
        name: str | None = None,
        resume: str | None = None,
        from_step: str | int | None = None,
        until_step: str | int | None = None,
        dry_run: bool = False,
        frozen: bool = False,
        no_display: bool = False,
        parallel: bool = True,
        fresh: bool = False,
        force: bool = False,
        lineage: Any = None,
        calibrated_by: Any = None,
        **overrides,
    ) -> SealedRun | None:
        """Run one attempt of the case through the workflow Pipeline.

        Returns what the run directory says once the attempt is closed, or
        ``None`` for a dry run and for a window that owns no run record.
        Never opens the index: the worker writes its directory, the caller
        indexes it afterwards.

        ``resume`` names the case to continue; the attempt resumes in place
        from the journal of its directory. ``fresh`` files everything the
        previous attempt left under ``attempts/<k>/`` and starts over.
        ``force`` claims a stale case whose death cannot be proven. ``lineage``
        and ``calibrated_by`` are the blocks a promotion seals its run with.
        """
        from hydromodpy.workflow.orchestrator import standard_steps
        from hydromodpy.workflow.steps.planning import resolve_run_config, step_build_plan
        from hydromodpy.workflow.steps.setup import rebuild_domain_if_stale

        project = self._project

        skip_display = bool(project._no_display) or bool(no_display)

        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

        if resume is not None:
            name = resume
        if name is None:
            # The configuration names its run: ``[simulation] name``, which a
            # TOML file defaults to its own stem. The counter only names a run
            # whose configuration carries no name at all.
            name = str(getattr(project._cfg.simulation, "name", "") or "").strip() or None
        if name is None:
            project._run_counter += 1
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=project._run_counter)

        all_steps = standard_steps()
        steps = all_steps
        until_idx = _bounded_step_index(until_step, all_steps, label="until_step")
        from_idx = _bounded_step_index(from_step, all_steps, label="from_step")
        if until_idx is not None:
            if from_idx is not None and from_idx > until_idx:
                raise ConfigError(
                    f"from_step {from_step!r} (index {from_idx}) is past until_step "
                    f"{until_step!r} (index {until_idx}): the window is empty."
                )
            steps = tuple(all_steps[: until_idx + 1])

        # A window that stops before ``setup_process`` reaches no step able to
        # open a run, so it is not a run and claims no directory.
        model_phase_index = _model_phase_index(all_steps)
        head_only = until_idx is not None and until_idx < model_phase_index
        if head_only and resume is not None:
            raise ConfigError(
                f"until_step {until_step!r} stops before 'setup_process', so the run keeps no "
                f"journal to resume from. Drop --resume, or widen the window."
            )
        needs_model_phase = not head_only
        # The Pipeline owns the model phase: it executes ``build_geographic``,
        # ``load_data`` and ``build_mesh`` itself, so each of them gets a
        # journal row and a process death inside one of them leaves a trace.
        # One run still needs the model built up front: ``step_build_plan``
        # below patches an existing model when the caller overrides it.
        plan_patches_model_phase = (
            bool(overrides) or thickness is not None or first_clim is not None
        )
        if needs_model_phase and plan_patches_model_phase:
            project._ensure_model_built()

        workspace_path = self._resolve_workspace_path()
        persisted = bool(project._cfg.simulation.results.persistence.save_catalog)
        claims = not head_only and not dry_run and persisted
        model_phase_ready = needs_model_phase and self._is_model_phase_ready()

        if dry_run:
            resume_from = from_idx if from_idx is not None else None
            if resume_from is None and model_phase_ready:
                resume_from = model_phase_index
            _print_dry_run_plan(run_id=name, steps=steps, resume_from=resume_from)
            return None

        # The configuration this run is defined by, overrides included. It is
        # what the Pipeline signs, what the run archives, and what every
        # builder reads. ``project._cfg`` stays the configuration the project
        # declares; the context carries the one of the run in flight.
        cfg_run = resolve_run_config(project._cfg, thickness=thickness)
        project._ctx.cfg = cfg_run
        rebuild_domain_if_stale(project._ctx)

        step_build_plan(
            project._ctx,
            name=name,
            overrides=overrides or {},
            thickness=thickness,
            first_clim=first_clim,
            solver=project._solver,
        )

        if properties is not None:
            project._ctx.setup.flow_runtime_overrides = {
                "source": "project_run",
                "properties": dict(properties),
            }
        else:
            project._ctx.setup.flow_runtime_overrides = None

        project._ctx.setup.run_id = name
        if project._store is not None:
            project._store.close()
            project._store = None

        site = getattr(getattr(cfg_run, "site", None), "name", None)
        run_overrides = _identity_overrides(overrides, first_clim=first_clim, properties=properties)
        # The identity of this run, computed once: the claim compares it to
        # the one of the previous attempt, the facts of the run record it.
        config_hash = (
            run_identity_hash(
                cfg_run.model_dump(mode="json"),
                overrides=run_overrides,
                inputs=input_file_digests(cfg_run),
            )
            if claims
            else None
        )
        bracket = (
            run_attempt(
                workspace_path,
                name,
                case_id=name,
                project=workspace_path.name,
                site=site,
                fresh=fresh,
                force=force,
                config_hash=config_hash,
                if_exists=cfg_run.simulation.if_exists,
            )
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
                model_phase_index=model_phase_index,
                skip_display=skip_display,
                frozen=frozen,
                parallel=parallel,
                run_overrides=run_overrides,
                config_hash=config_hash,
                lineage=lineage,
                calibrated_by=calibrated_by,
            )
        # The bracket has closed the outcome: what the directory says is final.
        if handle is None or sim_id is None:
            return None
        return sealed_run_of(handle.claim, workspace_path)

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
        parallel: bool,
        run_overrides: dict[str, Any] | None,
        config_hash: str | None,
        lineage: Any,
        calibrated_by: Any,
    ) -> str | None:
        """Drive the Pipeline inside the attempt bracket and return the ``sim_id`` of the run."""
        from hydromodpy.workflow.internals.state import PipelineState
        from hydromodpy.workflow.runner import Pipeline

        project = self._project
        run_dir = None if handle is None else handle.run_dir
        resumes = handle is not None and handle.claim.resumed
        if resume is not None and handle is not None and not resumes:
            if handle.claim.attempt == 1:
                raise ResumeError(
                    f"resume {resume!r}: {run_dir} holds no interrupted attempt to continue."
                )
            # The claim started this attempt over: the previous one ran another
            # configuration, or --fresh was asked. There is nothing to resume.
            logger.info(
                "resume %r: attempt %d of %s starts over from step 0",
                resume,
                handle.claim.attempt,
                run_dir.name if run_dir is not None else name,
            )

        self._bind_attempt(handle, workspace_path)

        # A model-phase-ready run reuses the model built in this process; its
        # resume_from > 0 is an in-process skip, not a journal resume of a prior
        # attempt (which would otherwise abort on an edited config).
        in_process_skip = False
        if from_idx is not None:
            resume_from: int | None = from_idx
        elif resumes and run_dir is not None:
            resume_from = _resolve_resume_step_index(
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

        initial = PipelineState(
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
                # This run is already named. ``run_setup`` derives a name from
                # the config when nobody gives it one, which would rename a run
                # the caller named differently.
                "run_name": name,
                # What this run changes on top of its configuration. It enters
                # the identity hash the seal records, so a run with an
                # override never passes for the run of the bare configuration.
                "run_overrides": run_overrides,
                "config_hash": config_hash,
                "run_dir": run_dir,
                "lineage": lineage,
                "calibrated_by": calibrated_by,
            },
        )

        # A head-only window owns no run record: handing it a directory would
        # let it overwrite the checkpoints of the run that carries this name.
        pipeline = Pipeline(steps, workspace=workspace_path, run_dir=run_dir)
        restore_frozen_root: Path | None = None
        if frozen:
            from hydromodpy.data.provenance.lockfile import frozen_project_root, set_frozen_mode

            restore_frozen_root = frozen_project_root()
            set_frozen_mode(True, project_root=workspace_path)

        try:
            final = pipeline.run(
                initial,
                resume_from=resume_from,
                parallel=parallel,
                model_phase_ready=in_process_skip,
                heartbeat=None if handle is None else handle.heartbeat,
            )
        finally:
            if frozen:
                from hydromodpy.data.provenance.lockfile import set_frozen_mode

                set_frozen_mode(
                    restore_frozen_root is not None,
                    project_root=restore_frozen_root,
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
