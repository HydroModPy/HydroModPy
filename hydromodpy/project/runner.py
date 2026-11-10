"""Run-phase orchestration for :class:`hydromodpy.project.Project`.

Holds the run-phase entry points backing the facade: :meth:`ProjectRunner.execute`
runs one attempt of a case through the workflow Pipeline and returns what its
directory says; :meth:`ProjectRunner.run` is the same followed by the index
refresh and the :class:`~hydromodpy.results.run.Run` view ``Project.simulate``
returns; :meth:`ProjectRunner.draft` says what a run would do and runs nothing.
The worker side (``hmp run``) stops at ``execute``: it never opens the index, the
launcher indexes after it.

An attempt takes its directory first, and only then learns what it asks for. Once
``runs/<name>/`` is claimed it writes ``request.json`` and ``config.toml``,
resolves its inputs, writes its request id into ``outcome.json``, starts over when
the previous attempt asked for something else (an asked resume is refused instead),
and, for a run that may be skipped, looks for a completed run of the same solution key.
A run that one answers undoes its claim without a trace and gives that run back.

The attempt protocol (claim of ``runs/<case>/``, pulse, outcome) is
:mod:`hydromodpy.workflow.record.attempt`; the seal is the last step of the pipeline.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from hydromodpy.core.config_kit.written import log_experimental_keys
from hydromodpy.core.exceptions import ConfigError, ResumeError
from hydromodpy.core.logging import get_logger
from hydromodpy.project.request import RunOutcome, RunRequest, write_request_file
from hydromodpy.project.run_overrides import override_changes
from hydromodpy.results.catalog.registration import check_name_free
from hydromodpy.results.storage.attempt import (
    record_request_id,
    refuse_resume_if_changed,
    scratch_dir_for_attempt,
)
from hydromodpy.workflow.record.attempt import AttemptHandle, run_attempt
from hydromodpy.workflow.record.manifest import config_sections_moved_since
from hydromodpy.workflow.record.resume import resolve_resume_step_index
from hydromodpy.workflow.solution_key import request_id_of, solution_key_of
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.prepare_solver.dispatch import solver_binaries
from hydromodpy.workflow.steps.prepare_solver.freeze import write_claim_config
from hydromodpy.workflow.steps.prepare_solver.restart import (
    WindowSource,
    resolve_restart_source,
    source_state_digests,
    window_input_entry,
    zone_run_ids,
)
from hydromodpy.workflow.window import model_phase_index, step_window

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.project.facade import Project
    from hydromodpy.project.launch.sites.expansion import PlanDraft
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
    from hydromodpy.project.facade import read_sealed_config
    from hydromodpy.results.record.manifest import is_sealed
    from hydromodpy.results.run.view import Run, open_run_dir
    from hydromodpy.results.storage.run_facts import read_facts
    from hydromodpy.results.storage.run_store import RunStore

    if is_sealed(run_dir):
        return open_run_dir(run_dir, read_config=read_sealed_config)
    if read_facts(run_dir) is None:
        return None
    store = RunStore.open(run_dir, workspace=project_root)
    return Run(sim_id, store)


def _attempt_bracket(workspace_path: Path, name: str, cfg_run: Any, *, fresh: bool, force: bool):
    """Return the context manager that claims ``runs/<name>/`` and closes its outcome.

    The claim always takes the next version of a completed name. ``if_exists = "fail"``
    is checked once the run knows it is not identical to a completed one
    (:meth:`ProjectRunner._claim_documents`), so an identical run is given back before
    that refusal is read.
    """
    return run_attempt(
        workspace_path,
        name,
        case_id=name,
        project=workspace_path.name,
        site=getattr(getattr(cfg_run, "site", None), "name", None),
        fresh=fresh,
        force=force,
        if_exists="version",
    )


def _refuse_resume_of_nothing(handle: AttemptHandle, resume: str, name: str) -> None:
    """Refuse a ``resume`` whose directory holds no interrupted attempt, or say it starts over."""
    claim = handle.claim
    if claim.attempt == 1:
        raise ResumeError(
            f"resume {resume!r}: {handle.run_dir} holds no interrupted attempt to continue."
        )
    # The claim started this attempt over because --fresh was asked. A resume whose
    # request changed is refused before this point. There is nothing to resume.
    logger.info(
        "resume %r: attempt %d of %s starts over from step 0",
        resume,
        claim.attempt,
        handle.run_dir.name if handle.run_dir is not None else name,
    )


class ProjectRunner:
    """Run-phase methods bound to a :class:`Project` instance.

    Composed by :class:`Project` (``project._runner``). Holds no state of
    its own besides the back-reference to ``project``; every call reads or
    mutates the project's workflow context directly.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    # -- High-level workflow entry points ---------------------------------

    def request_of(self, **options: Any) -> RunRequest:
        """Return the request a call of :meth:`run` or :meth:`execute` makes by keywords.

        The document is the one this project was loaded from. The request is made
        for a configuration already built, so ``request.json`` is not written for it.
        The keywords are the members of :class:`~hydromodpy.project.request.RunRequest`:
        ``set``, ``name``, ``resume``, ``from_step``, ``until_step``, ``frozen``,
        ``no_display``, ``fresh`` and ``force``. A name that breaks the rule of a run
        name is refused with :class:`~hydromodpy.core.exceptions.ConfigError`.
        """
        document = copy.deepcopy(dict(getattr(self._project._ctx, "raw_toml", None) or {}))
        given = {key: value for key, value in options.items() if value is not None}
        given["set"] = dict(given.get("set") or {})
        try:
            return RunRequest(config=document, form="object", **given)
        except ValidationError as exc:
            message = "; ".join(
                str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()
            )
            raise ConfigError(message) from exc

    def run(
        self,
        request: RunRequest | None = None,
        *,
        lineage: Any = None,
        calibrated_by: Any = None,
        **options: Any,
    ) -> Run | None:
        """Run one attempt and return the :class:`Run` view of its directory.

        *request* is what to run, or the keywords of :meth:`request_of` make one. The
        index of the project is refreshed from the run directory, but the view reads
        the directory itself: a sealed run through its seal, a run that stopped
        before its seal (``until_step``) through its store. An index handle opened
        earlier in this process keeps the snapshot it opened on, so it may not hold
        the run yet. A run that wrote no directory, or no facts to read, returns
        ``None``.
        """
        sealed = self.execute(request, lineage=lineage, calibrated_by=calibrated_by, **options)
        if sealed is None:
            return None
        from hydromodpy.project import phases as project_phases
        from hydromodpy.results.catalog.indexer import index_new_runs

        project = self._project
        index_new_runs(sealed.project_root)
        project_phases.open_catalog(project)
        run_view = run_view_of(
            sealed.run_dir, project_root=sealed.project_root, sim_id=str(sealed.sim_id)
        )
        if run_view is not None:
            project._run_history.append(run_view)
        return run_view

    def _run_name(self, name: str | None, resume: str | None) -> str | None:
        """Return the name of a run: asked, or what the configuration calls it.

        A bare resume (``""``) names no run of its own: it continues the run the
        request names, so the name comes from ``name`` or the configuration.
        """
        if resume:
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
        from hydromodpy.project.dispatch.workflow import completed_identical_run
        from hydromodpy.project.launch.sites.expansion import single_case_draft
        from hydromodpy.workflow.solution_key import planned_solution_key
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
            done=completed_identical_run(
                Path(cfg_run.workspace.project_root), run_name, planned_solution_key(cfg_run)
            )
            is not None,
        )

    def execute(
        self,
        request: RunRequest | None = None,
        *,
        lineage: Any = None,
        calibrated_by: Any = None,
        frozen: bool | None = None,
        skip_identical: bool = False,
        window_source: WindowSource | None = None,
        replay_of: Path | None = None,
        strict: bool = False,
        **options: Any,
    ) -> RunOutcome | None:
        """Run one attempt of the case through the workflow Pipeline.

        *request* is what to run, or the keywords of :meth:`request_of` make one. Returns
        what the run directory says once the attempt is closed, or ``None`` for a window
        that owns no run record. Never opens the index: the worker writes its
        directory, the caller indexes it afterwards.

        ``resume`` names the case to continue; the attempt resumes in place
        from the journal of its directory. ``fresh`` files everything the
        previous attempt left under ``attempts/<k>/`` and starts over.
        ``force`` claims a stale case whose death cannot be proven. ``lineage``
        and ``calibrated_by`` are the blocks a promotion seals its run with.
        ``frozen`` wins over the member of the request when given: a replay that
        checked its record runs unfrozen. ``skip_identical`` lets the attempt give back a
        completed run of the same solution key instead of computing: the caller says so for
        a plain run, never for a resume, a window or a replay. ``window_source`` is the run
        window ``k - 1`` of a chain left, which window ``k > 1`` starts from: its state
        digest enters the request id and the run takes it as the input ``initial_state``.
        ``replay_of`` is the run or published copy a replay plays again: its inputs are
        pinned from its ``inputs.json``, and ``strict`` refuses a value that did not
        reproduce it, at the seal.

        A frozen request reads the lockfile once, before the claim, and the inputs it
        holds travel on the setup context to the data step: the run never changes a
        global, so two runs of one process stay apart.
        """
        from hydromodpy.data.provenance.lockfile import read_locked_inputs
        from hydromodpy.workflow.steps.sequence import standard_steps

        project = self._project
        request = request if request is not None else self.request_of(**options)
        frozen_inputs = request.frozen if frozen is None else frozen

        # What the launch asks of the figures. It reaches the display step and
        # nothing else: it is no part of the identity or of the sealed config.
        skip_display = bool(project._no_display or project._headless or request.no_display)

        changes = override_changes(project._cfg, request.set)

        name = self._run_name(request.name, request.resume)
        if name is None:
            project._run_counter += 1
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=project._run_counter)

        all_steps = standard_steps()
        steps = all_steps
        from_idx, until_idx, head_only = step_window(
            all_steps, request.from_step, request.until_step, request.resume
        )
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
        overrides = request.overrides(changes)
        if lineage is None and overrides:
            from hydromodpy.schema.lineage import Lineage

            lineage = Lineage(overrides=overrides)
        elif lineage is not None and overrides:
            lineage = lineage.model_copy(update={"overrides": {**lineage.overrides, **overrides}})

        if replay_of is not None:
            from hydromodpy.workflow.replay_checks import locked_inputs_of

            pinned = locked_inputs_of(
                replay_of,
                project_root=Path(cfg_run.workspace.project_root),
                data_dir=Path(cfg_run.workspace.data_path),
            )
        elif frozen_inputs:
            pinned = read_locked_inputs(workspace_path)
        else:
            pinned = None
        project._ctx.setup.locked_inputs = pinned
        bracket = (
            _attempt_bracket(
                workspace_path, name, cfg_run, fresh=request.fresh, force=request.force
            )
            if claims
            else nullcontext(None)
        )
        identical: Path | None = None
        sim_id: str | None = None
        try:
            with bracket as handle:
                solution_key = None
                if handle is not None:
                    solution_key, identical = self._claim_documents(
                        handle,
                        request,
                        cfg_run,
                        workspace_path,
                        name=name,
                        skip_identical=skip_identical,
                        window_source=window_source,
                    )
                if identical is not None:
                    handle.withdraw()
                else:
                    sim_id = self._execute_attempt(
                        handle,
                        name=name,
                        steps=steps,
                        all_steps=all_steps,
                        cfg_run=cfg_run,
                        workspace_path=workspace_path,
                        resume=request.resume,
                        from_idx=from_idx,
                        model_phase_ready=model_phase_ready,
                        model_phase_index=model_phase_index(all_steps),
                        skip_display=skip_display,
                        window_source=window_source,
                        run_overrides=changes or None,
                        solution_key=solution_key,
                        lineage=lineage,
                        calibrated_by=calibrated_by,
                        replay_of=replay_of,
                        strict=strict,
                    )
        finally:
            # The inputs belong to the run that resolved them: a later phase of this
            # project resolves its own.
            project._ctx.inputs = None
            project._ctx.setup.locked_inputs = None
        if identical is not None:
            project._ctx.run_dir = None
            return RunOutcome.read(
                identical, project_root=workspace_path, identical_to=identical.name
            )
        # The bracket has closed the outcome: what the directory says is final.
        if handle is None or sim_id is None:
            return None
        return RunOutcome.read(handle.claim.run_dir, project_root=workspace_path)

    def _claim_documents(
        self,
        handle: AttemptHandle,
        request: RunRequest,
        cfg_run: Any,
        workspace_path: Path,
        *,
        name: str,
        skip_identical: bool,
        window_source: WindowSource | None = None,
    ) -> tuple[str, Path | None]:
        """Say what the claimed attempt asks for, and whether a completed run already answers.

        In the order of the module: ``request.json`` and ``config.toml`` are written, the
        inputs are resolved and put on the context, the request id goes into
        ``outcome.json``, an attempt ``k + 1`` that is no asked resume starts over when the
        previous attempt asked for something else and an asked resume is refused, then the solution key is told and, for a run that may be
        skipped, a completed run of that key is looked for. ``if_exists = "fail"`` is
        checked last, so a run identical to a completed one is given back and not refused.
        Returns the solution key and the directory of the identical run, or ``None``.
        """
        from hydromodpy.data.loading.inputs import resolve_inputs
        from hydromodpy.project.dispatch.workflow import completed_identical_run

        project = self._project
        ctx = project._ctx
        project_root = Path(cfg_run.workspace.project_root)
        self._write_claim_documents(handle, request, cfg_run, project_root)
        # A download that fails closes the outcome as failed: the claim came first.
        resolved = resolve_inputs(
            cfg_run,
            bounds=ctx.bounds,
            data_dir=Path(cfg_run.workspace.data_path),
            locked=ctx.setup.locked_inputs,
        )
        ctx.inputs = resolved
        request_id = request_id_of(
            cfg_run,
            resolved,
            search=False,
            window_state=None
            if window_source is None
            else window_input_entry(project_root, window_source).sha256,
            source_states=source_state_digests(cfg_run, project_root),
        )
        record_request_id(handle.run_dir, request_id)
        # Starting over keeps config.toml and request.json: they are already this attempt's.
        # A resume the caller asked for never starts over: it is refused when an input, a key
        # or the state of a window changed since the stop, and names the sections of the
        # configuration that moved. The checkpoint check stays a second net.
        if request.resume is None:
            handle.start_over_if_changed(request_id)
        else:
            try:
                refuse_resume_if_changed(
                    handle.claim,
                    request_id,
                    moved_sections=config_sections_moved_since(handle.run_dir, cfg_run),
                )
            except ResumeError:
                handle.withdraw()
                raise
        key = solution_key_of(cfg_run, request_id, binaries=solver_binaries(cfg_run))
        if skip_identical and not request.force:
            identical = completed_identical_run(project_root, name, key)
            if identical is not None:
                return key, identical
        if cfg_run.simulation.if_exists == "fail" and handle.claim.created:
            try:
                check_name_free(workspace_path, name, excluding=handle.run_dir.name)
            except Exception:
                # The refusal leaves nothing behind: the claim goes with it.
                handle.withdraw()
                raise
        return key, None

    def _write_claim_documents(
        self, handle: AttemptHandle, request: RunRequest, cfg_run: Any, project_root: Path
    ) -> None:
        """Write ``request.json`` and ``config.toml`` into the directory the attempt claimed."""
        ctx = self._project._ctx
        ctx.run_dir = handle.run_dir
        write_request_file(handle.run_dir, request)
        restart_sim_id = restart_path = None
        reference = getattr(getattr(cfg_run, "flow", None), "restart_from", None)
        if reference:
            source = resolve_restart_source(project_root, reference)
            restart_sim_id, restart_path = source.sim_id, str(source.path)
        write_claim_config(
            ctx,
            project_root=project_root,
            restart_sim_id=restart_sim_id,
            restart_path=restart_path,
            zone_runs=zone_run_ids(cfg_run, project_root),
        )

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
        project._ctx.setup.slot_request = None
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
        window_source: WindowSource | None,
        run_overrides: dict[str, Any] | None,
        solution_key: str | None,
        lineage: Any,
        calibrated_by: Any,
        replay_of: Path | None,
        strict: bool,
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
            name,
            cfg_run,
            skip_display,
            run_overrides,
            solution_key,
            run_dir,
            lineage,
            calibrated_by,
            window_source,
            replay_of,
            strict,
        )

        # A head-only window owns no run record: handing it a directory would
        # let it overwrite the checkpoints of the run that carries this name.
        pipeline = Pipeline(steps, workspace=workspace_path, run_dir=run_dir)
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
        solution_key: str | None,
        run_dir: Path | None,
        lineage: Any,
        calibrated_by: Any,
        window_source: WindowSource | None,
        replay_of: Path | None,
        strict: bool,
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
                # What the seal records as the identity of the run.
                "solution_key": solution_key,
                "run_dir": run_dir,
                "lineage": lineage,
                "calibrated_by": calibrated_by,
                # The run window k - 1 of a chain left, for window k > 1.
                "window_source": window_source,
                # The run or copy this run plays again, and whether a value that
                # did not reproduce it is refused at the seal.
                "replay_of": replay_of,
                "strict": strict,
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
        return Path(project._ctx.config_path).parent
