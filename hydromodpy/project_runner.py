"""Run-phase orchestration for :class:`hydromodpy.project.Project`.

Holds the high-level workflow entry points: ``run``, ``simulate``,
``sweep``, ``calibrate``, ``mesh`` and ``report``. The prepared-run
primitives (``prepare``, ``execute``, ``ingest``, ``render``,
``cleanup``) live in :mod:`hydromodpy.project_prepared_run` and are
composed into the runner so the legacy ``project._runner.prepare(...)``
access pattern keeps working.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import ConfigError, ConfigMissingError, ResumeError
from hydromodpy.core.logging import get_logger
from hydromodpy.project_prepared_run import DEFAULT_RUN_NAME_TEMPLATE, ProjectPreparedRun

if TYPE_CHECKING:
    from hydromodpy.project import Project
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


@contextmanager
def _pin_parent_sim_id(ctx: object, parent_sim_id: str | None) -> Iterator[None]:
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


def _resolve_resume_step_index(
    workspace: Path,
    run_id: str,
    *,
    steps_blueprint: tuple[str, ...] | None = None,
) -> int:
    """Locate the next step index to execute for a previously interrupted run.

    The workflow journal in ``catalog.duckdb`` is the single source of truth:
    when no row exists for ``run_id`` the run is treated as fresh and starts
    from step 0.
    """
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.journal import WorkflowJournal
    from hydromodpy.workflow.resume import ResumePlanner

    try:
        catalog = SimulationCatalog(workspace)
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
        self._prepared = ProjectPreparedRun(project)

    # -- Prepared-run primitives (delegated) ------------------------------

    def prepare(self, *, name: str | None = None, **overrides) -> str:
        """Reserve a sim_id, register the simulation and persist all inputs."""
        return self._prepared.prepare(name=name, **overrides)

    def execute(self, sim_id: str) -> float:
        """Run the solver for a previously prepared simulation."""
        return self._prepared.execute(sim_id)

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations for a completed simulation."""
        return self._prepared.ingest(sim_id, extractors=extractors)

    def render(
        self,
        sim_id: str,
        *,
        figures: list[str] | None = None,
    ) -> list[Path]:
        """Render the display figures attached to this simulation."""
        return self._prepared.render(sim_id, figures=figures)

    def cleanup(
        self,
        sim_id: str,
        *,
        keep_solver_files: bool = False,
        status: str = "completed",
    ) -> None:
        """Finalize the run status and remove the scratch directory."""
        return self._prepared.cleanup(
            sim_id,
            keep_solver_files=keep_solver_files,
            status=status,
        )

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
        **overrides,
    ) -> Run | None:
        """Run the simulation through the canonical workflow Pipeline."""
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
        if until_step is not None:
            until_idx = _resolve_step_index(until_step, all_steps)
            steps = tuple(all_steps[: until_idx + 1])

        workspace_path = self._resolve_workspace_path()

        if from_step is not None:
            resume_from: int | None = _resolve_step_index(from_step, all_steps)
            run_id = resume or name
        elif resume is not None:
            resume_from = _resolve_resume_step_index(
                workspace_path,
                resume,
                steps_blueprint=tuple(getattr(step, "name", "") for step in all_steps),
            )
            run_id = resume
        elif self._is_model_phase_ready():
            resume_from = _resolve_step_index("setup_process", all_steps)
            run_id = name
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
                "cfg": project.cfg,
                "config_path": project._config_path,
                "raw_toml": getattr(project._ctx, "raw_toml", {}) or {},
                "skip_display": skip_display,
                "spatial_support_registry": project._spatial_support_registry,
                "requested_spatial_support_ids": project._requested_support_ids,
                "requested_domain_supports": project._requested_domain_supports,
            },
        )

        pipeline = Pipeline(steps, workspace=workspace_path)
        previous_frozen_mode: bool | None = None
        if frozen:
            from hydromodpy.data.data_freeze import is_frozen_mode, set_frozen_mode

            previous_frozen_mode = is_frozen_mode()
            set_frozen_mode(True)

        try:
            final = pipeline.run(initial, resume_from=resume_from)
        except Exception:
            from hydromodpy import project_phases

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
            from hydromodpy import project_phases

            if project._store is None:
                project_phases.open_catalog(project)
            _rebind_run_history_catalog(project)
            if previous_frozen_mode is not None:
                from hydromodpy.data.data_freeze import set_frozen_mode

                set_frozen_mode(previous_frozen_mode)

        final_ctx = final.get("ctx") if final is not None else None
        sim_id = getattr(final_ctx, "sim_id", None) if final_ctx is not None else None
        if sim_id is None or project._store is None:
            return None
        run_view = project._store[sim_id]
        project._run_history.append(run_view)
        _rebind_run_history_catalog(project)
        return run_view

    def simulate(
        self,
        *,
        time: tuple | None = None,
        processes: list | None = None,
        name: str | None = None,
        **overrides,
    ) -> Run:
        """Run one simulation with orchestration specified from Python."""
        from hydromodpy.simulation.planning.config import (
            SimulationProcessConfig,
            SimulationTimeConfig,
        )

        project = self._project

        if time is not None:
            start, end, step = time
            project.cfg.simulation.time = SimulationTimeConfig(
                start_datetime=start,
                end_datetime=end,
                step_value=step,
                coverage_policy=getattr(project.cfg.simulation.time, "coverage_policy", "warn"),
            )
            from hydromodpy.core.time import (
                apply_explicit_time_window_to_tgrids,
                require_flow_simulation_time_grid,
            )

            apply_explicit_time_window_to_tgrids(project.cfg)
            project._time_grid = require_flow_simulation_time_grid(project.cfg)
            project._ctx.setup.time_grid = project._time_grid

        if processes is not None:
            resolved: list[SimulationProcessConfig] = []
            for idx, entry in enumerate(processes):
                if isinstance(entry, str):
                    proc_type, solver_name = entry, project._solver
                else:
                    proc_type, solver_name = entry
                if str(proc_type).strip().lower() == "mesh":
                    resolved.append(
                        SimulationProcessConfig(
                            id=f"{proc_type}_{idx}",
                            type=proc_type,
                            backend=str(solver_name or "catchment"),
                        )
                    )
                else:
                    resolved.append(
                        SimulationProcessConfig(
                            id=f"{proc_type}_{idx}",
                            type=proc_type,
                            solvers=[solver_name],
                        )
                    )
            project.cfg.simulation.process = resolved

        return self.run(name=name, **overrides)

    def sweep(
        self,
        parameters: dict[str, list[float] | dict],
        *,
        strategy: str = "enumerate",
        name_template: str = "{param}_{value:.4g}",
        parallel: int = 1,
    ):
        """Run N simulations from a parameter table."""
        from hydromodpy.results.simulation_group import SimulationGroup
        from hydromodpy.workflow.parallel import run_sweep

        if parallel != 1:
            raise NotImplementedError("Parallel sweep requires worker pool setup")
        sim_ids = run_sweep(
            self._project,
            parameters=parameters,
            strategy=strategy,
            name_template=name_template,
        )
        return SimulationGroup(sim_ids, self._project._store)

    def mesh(self) -> dict:
        """Run the standalone mesh-only workflow defined by this project."""
        project = self._project
        if project._config_path is not None:
            from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

            return MeshCatchmentLauncher(project._config_path).run()
        if project.cfg.mesh_catchment is None:
            raise ConfigMissingError(
                "Project.mesh() requires cfg.mesh_catchment when Project was "
                "created from an in-memory HydroModPyConfig."
            )

        project.build_mesh()
        return dict(project._ctx.setup.mesh_summary or {})

    def report(self, session_id: str | None = None) -> Path:
        """Render the HTML report for a calibration session."""
        from hydromodpy.calibration.report import resolve_calibration_session_id
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.workflow.steps.calibration import (
            step_render_calibration_report,
        )

        project = self._project
        workspace_root = self._resolve_workspace_path()
        catalog = project._store
        owns_catalog = catalog is None
        if owns_catalog:
            catalog = SimulationCatalog(workspace_root)
        try:
            full_id = resolve_calibration_session_id(catalog, session_id)
            return step_render_calibration_report(
                catalog=catalog,
                session_id=full_id,
                workspace_root=workspace_root,
            )
        finally:
            if owns_catalog:
                catalog.close()

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
        """Return the project runtime root used for checkpoints and ledger."""
        project = self._project
        workspace = project._ctx.setup.workspace
        if workspace is not None:
            return Path(workspace.project_root)
        if project._config_path is not None:
            return project._config_path.parent
        return Path.cwd()
