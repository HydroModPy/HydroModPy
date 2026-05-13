"""Run-phase facade for a :class:`hydromodpy.project.Project`.

Exposes the lower-level run primitives that compose ``Project.run``:
``prepare`` / ``execute`` / ``ingest`` / ``render`` / ``cleanup`` and the
higher-level ``simulate`` and ``sweep`` orchestrations. Keep ``Project``
focused on model-phase verbs and lifecycle; advanced run orchestration
moves here.

Construct via :meth:`Project.session`. The session shares the parent's
runner, context and configuration; it owns no state of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.project import Project
    from hydromodpy.project_runner import ProjectRunner
    from hydromodpy.results.run import Run


class ProjectSession:
    """Run-phase orchestrator bound to one :class:`Project` instance."""

    __slots__ = ("_project", "_runner")

    def __init__(self, project: Project) -> None:
        self._project = project
        self._runner: ProjectRunner = project._runner

    @property
    def project(self) -> Project:
        """The owning :class:`Project`."""
        return self._project

    def prepare(self, *, name: str | None = None, **overrides) -> str:
        """Reserve a ``sim_id``, register the simulation and persist inputs."""
        return self._runner.prepare(name=name, **overrides)

    def execute(self, sim_id: str) -> float:
        """Run the solver for a previously prepared simulation."""
        return self._runner.execute(sim_id)

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations and derived results for a completed simulation."""
        return self._runner.ingest(sim_id, extractors=extractors)

    def render(
        self,
        sim_id: str,
        *,
        figures: list[str] | None = None,
    ) -> list[Path]:
        """Render the display figures attached to this simulation."""
        return self._runner.render(sim_id, figures=figures)

    def cleanup(
        self,
        sim_id: str,
        *,
        keep_solver_files: bool = False,
        status: str = "completed",
    ) -> None:
        """Finalize the run status and remove the scratch directory."""
        return self._runner.cleanup(
            sim_id,
            keep_solver_files=keep_solver_files,
            status=status,
        )

    def simulate(
        self,
        *,
        time: tuple | None = None,
        processes: list | None = None,
        name: str | None = None,
        **overrides,
    ) -> Run:
        """Run one simulation with orchestration specified from Python."""
        return self._runner.simulate(
            time=time,
            processes=processes,
            name=name,
            **overrides,
        )

    def sweep(
        self,
        parameters: dict[str, list[float] | dict],
        *,
        strategy: str = "enumerate",
        name_template: str = "{param}_{value:.4g}",
        parallel: int = 1,
    ):
        """Run a parameter sweep from one project configuration."""
        return self._runner.sweep(
            parameters,
            strategy=strategy,
            name_template=name_template,
            parallel=parallel,
        )

    def __repr__(self) -> str:
        return f"ProjectSession(project={self._project!r})"


__all__ = ["ProjectSession"]
