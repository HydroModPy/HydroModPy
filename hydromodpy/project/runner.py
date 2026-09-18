"""Run-phase orchestration for :class:`hydromodpy.project.Project`.

Holds the internal run-phase entry points backing the facade: ``run`` (the
engine method that ``Project.simulate`` delegates to) and ``sweep``. The
facade verb is :meth:`Project.simulate`.

TOML-driven workflows that do not benefit from setup-once state (overview,
mesh, comparison) are reached through :func:`hydromodpy.run` on the
``[workflow] mode``, not through ``Project``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hydromodpy.core.exceptions import ConfigError, ResumeError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.project.facade import Project
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

DEFAULT_RUN_NAME_TEMPLATE = "run_{counter:04d}"


@contextmanager
def _pin_parent_sim_id(ctx: Any, parent_sim_id: str | None) -> Iterator[None]:
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


def _resolve_resume_step_index(
    workspace: Path,
    run_id: str,
    *,
    steps_blueprint: tuple[str, ...] | None = None,
) -> int:
    """Locate the next step index to execute for a previously interrupted run.

    The workflow journal in the project index is the single source of truth:
    when no row exists for ``run_id`` the run is treated as fresh and starts
    from step 0.
    """
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.tracking.journal import WorkflowJournal
    from hydromodpy.workflow.tracking.resume import ResumePlanner

    try:
        catalog = Catalog(workspace)
    except Exception as exc:
        raise ResumeError(
            f"Could not open the catalog at {workspace} to resume '{run_id}': {exc}"
        ) from exc

    try:
        journal = WorkflowJournal(catalog)
        planner = ResumePlanner(journal, workspace)
        plan = planner.compute(
            run_id=run_id,
            current_config_sha256=None,
            steps_blueprint=steps_blueprint or (),
        )
    finally:
        try:
            catalog.close()
        except Exception:
            pass

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


def _rebind_run_history_catalog(project: Project) -> None:
    """Bind previously returned Run handles to the current project catalog."""
    store = project._store
    if store is None:
        return
    project._ctx.store = store
    for run in project._run_history:
        run._catalog = store


class ProjectRunner:
    """Run-phase methods bound to a :class:`Project` instance.

    Composed by :class:`Project` (``project._runner``). Holds no state of
    its own besides the back-reference to ``project`` and a delegate for
    the prepared-run primitives; every call reads or mutates the
    project's workflow context directly.
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
        **overrides,
    ) -> Run | None:
        """Run the simulation through the canonical workflow Pipeline.

        ``parallel`` (default True) lets the Pipeline dispatch independent
        Kahn cohorts through a thread pool. Pass ``parallel=False`` to
        force the legacy sequential path (useful for debugging).
        """
        from hydromodpy.workflow.internals.state import PipelineState
        from hydromodpy.workflow.orchestrator import standard_steps
        from hydromodpy.workflow.runner import Pipeline
        from hydromodpy.workflow.steps.planning import step_build_plan

        project = self._project

        skip_display = bool(project._no_display) or bool(no_display)

        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

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
        # register a simulation, so it is not a run and writes no run record -
        # see the Pipeline workspace below.
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
        # Building them here first would put that work before the Pipeline has
        # started, where nothing records it.
        #
        # One run still needs the model built up front: ``step_build_plan``
        # below patches an existing model when the caller overrides it - it
        # rebuilds the domain on a new thickness and replays the data binders
        # on the loaded forcings. Such a run is always a repeat on a Project
        # whose model phase is already there (``sweep`` builds it explicitly),
        # so this only covers a hand-written override on an untouched Project.
        plan_patches_model_phase = (
            bool(overrides) or thickness is not None or first_clim is not None
        )
        if needs_model_phase and plan_patches_model_phase:
            project._ensure_model_built()

        workspace_path = self._resolve_workspace_path()

        # A model-phase-ready run reuses the model built in this process; its
        # resume_from > 0 is an in-process skip, not a journal resume of a prior
        # same-name run (which would otherwise abort on an edited config).
        model_phase_ready = False
        if from_idx is not None:
            resume_from: int | None = from_idx
            run_id = resume or name
        elif resume is not None:
            resume_from = _resolve_resume_step_index(
                workspace_path,
                resume,
                steps_blueprint=tuple(getattr(step, "name", "") for step in all_steps),
            )
            run_id = resume
        elif needs_model_phase and self._is_model_phase_ready():
            resume_from = model_phase_index
            run_id = name
            model_phase_ready = True
        else:
            resume_from = None
            run_id = name

        if dry_run:
            _print_dry_run_plan(
                run_id=run_id,
                steps=steps,
                resume_from=resume_from,
            )
            return None

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
        project._ctx.store = None

        initial = PipelineState(
            run_id=run_id,
            data={
                "ctx": project._ctx,
                "cfg": project._cfg,
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
                # ``BuildMeshStep`` reads its mesh sections from the state; the
                # facade verb reads the same three off the Project. A Pipeline
                # that builds the mesh without them would ignore
                # [mesh_catchment] and [mesh_input] entirely.
                "mesh_section_data": project._mesh_section_data,
                "constraints_mode": project._mesh_constraints_mode,
                "external_mesh_input": project._external_mesh_input,
                # This run is already named. ``run_setup`` derives a name from
                # the config when nobody gives it one, which would rename a run
                # the caller named differently.
                "run_name": name,
            },
        )

        # A head-only window registers no simulation, so it owns no run record.
        # Handing it the workspace would let it overwrite the manifest of the
        # run that carries this name and invalidate that run's journal.
        pipeline = Pipeline(steps, workspace=None if head_only else workspace_path)
        restore_frozen_root: Path | None = None
        if frozen:
            from hydromodpy.data.data_freeze import frozen_project_root, set_frozen_mode

            restore_frozen_root = frozen_project_root()
            set_frozen_mode(True, project_root=workspace_path)

        try:
            final = pipeline.run(
                initial,
                resume_from=resume_from,
                parallel=parallel,
                model_phase_ready=model_phase_ready,
            )
        except Exception:
            from hydromodpy.project import phases as project_phases

            project_phases.open_catalog(project)
            failed_sim_id = getattr(project._ctx, "sim_id", None)
            if failed_sim_id is not None and project._store is not None:
                try:
                    project._store.finalize(failed_sim_id, status="failed")
                except Exception:
                    logger.debug(
                        "Could not mark failed simulation %s after pipeline error",
                        failed_sim_id,
                        exc_info=True,
                    )
            raise
        finally:
            from hydromodpy.project import phases as project_phases

            if project._store is None:
                project_phases.open_catalog(project)
            _rebind_run_history_catalog(project)
            if frozen:
                from hydromodpy.data.data_freeze import set_frozen_mode

                set_frozen_mode(
                    restore_frozen_root is not None,
                    project_root=restore_frozen_root,
                )

        if not model_phase_ready:
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
        if sim_id is None or project._store is None:
            return None
        run_view = project._store[sim_id]
        project._run_history.append(run_view)
        _rebind_run_history_catalog(project)
        return run_view

    def sweep(
        self,
        parameters: dict[str, list[float] | dict],
        *,
        strategy: str = "enumerate",
        name_template: str = "{param}_{value:.4g}",
        parallel: int = 1,
    ):
        """Run N simulations from a parameter table.

        ``parallel > 1`` enables the thread-pool backend in
        :func:`hydromodpy.workflow.parallel.run_sweep`. Threads are
        chosen over processes because the live ``Project`` (DuckDB
        catalog, Zarr store, in-memory ``WorkflowContext``) is not
        pickle-safe.
        """
        from hydromodpy.results.run.group import RunSet
        from hydromodpy.workflow.parallel import run_sweep

        self._project._ensure_model_built()
        sim_ids = run_sweep(
            cast(Any, self._project),
            parameters=parameters,
            strategy=strategy,
            name_template=name_template,
            parallel=parallel,
        )
        return RunSet(sim_ids, self._project._store)

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
        """Return the project runtime root used for checkpoints and ledger.

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
