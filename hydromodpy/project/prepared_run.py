"""Prepared-run primitives extracted from :class:`ProjectRunner`.

Holds the low-level lifecycle helpers (``prepare``, ``execute``,
``ingest``, ``render``, ``cleanup``) that drive a single simulation
between user-controlled phases. Split from :mod:`hydromodpy.project.runner`
so the runner stays focused on high-level workflow orchestration.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from hydromodpy.project.facade import Project


DEFAULT_RUN_NAME_TEMPLATE = "run_{counter:04d}"


class ProjectPreparedRun:
    """Prepared-run primitives bound to a :class:`Project` instance.

    Composed by :class:`ProjectRunner`. Holds no state of its own besides
    the back-reference to ``project``: every call reads or mutates the
    project's workflow context directly.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def prepare(self, *, name: str | None = None, **overrides) -> str:
        """Reserve a sim_id, register the simulation and persist all inputs."""
        from hydromodpy.workflow.orchestrator import prepare_run

        project = self._project
        project._run_counter += 1
        sim_id = str(uuid4())
        if name is None:
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=project._run_counter)

        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

        project._ctx.store = project._store
        final_name = prepare_run(
            project._ctx,
            sim_id=sim_id,
            name=name,
            project_name=project._project_name,
            overrides=overrides,
            thickness=thickness,
            first_clim=first_clim,
            solver=project._solver,
            properties=properties,
        )
        project._active_runs[sim_id] = final_name
        return sim_id

    def execute(self, sim_id: str) -> float:
        """Run the solver for a previously prepared simulation."""
        from hydromodpy.workflow.orchestrator import execute_run

        project = self._project
        final_name = project._active_runs.get(sim_id, project._ctx.setup.run_id)
        wall = execute_run(project._ctx, sim_id, final_name=final_name)
        project._last_wall_seconds[sim_id] = wall
        return wall

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations for a completed simulation."""
        from hydromodpy.workflow.orchestrator import ingest_run

        ingest_run(self._project._ctx, sim_id, extractors=extractors)

    def render(
        self,
        sim_id: str,
        *,
        figures: list[str] | None = None,
    ) -> list[Path]:
        """Render the display figures attached to this simulation."""
        from hydromodpy.workflow.orchestrator import render_run

        project = self._project
        run = project._store[sim_id]
        final_name = project._active_runs.get(sim_id, project._ctx.setup.run_id)
        return render_run(
            project._ctx,
            sim_id,
            run=run,
            figures=figures,
            headless=project._headless,
            no_display=project._no_display,
            run_name=final_name,
        )

    def cleanup(
        self,
        sim_id: str,
        *,
        keep_solver_files: bool = False,
        status: str = "completed",
    ) -> None:
        """Finalize the run status and remove the scratch directory."""
        from hydromodpy.workflow.orchestrator import cleanup_run

        project = self._project
        wall = project._last_wall_seconds.pop(sim_id, 0.0)
        cleanup_run(
            project._ctx,
            sim_id,
            keep_solver_files=keep_solver_files,
            wall_seconds=wall,
            save_artifacts=False,
            close_store=False,
            status=status,
        )
        project._active_runs.pop(sim_id, None)
