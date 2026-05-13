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
    """Run-phase orchestrator bound to one :class:`Project` instance.

    Construct via :meth:`Project.session`. The session shares the parent
    project's runner and runtime context; calling any of its methods after
    closing the underlying project raises.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> project = hmp.Project("hydromodpy.toml")
    >>> session = project.session()
    >>> sim_id = session.prepare(name="probe")
    >>> session.execute(sim_id)
    >>> session.ingest(sim_id)
    """

    __slots__ = ("_project", "_runner")

    def __init__(self, project: Project) -> None:
        self._project = project
        self._runner: ProjectRunner = project._runner

    @property
    def project(self) -> Project:
        """The owning :class:`Project`."""
        return self._project

    def prepare(self, *, name: str | None = None, **overrides) -> str:
        """Reserve a ``sim_id``, register the simulation and persist inputs.

        Parameters
        ----------
        name
            Optional human-readable run name persisted in the catalog.
        overrides
            Flow parameter overrides applied to the simulation plan.

        Returns
        -------
        str
            UUID of the prepared simulation.

        Raises
        ------
        PipelineError
            If preparation cannot persist the run row.
        """
        return self._runner.prepare(name=name, **overrides)

    def execute(self, sim_id: str) -> float:
        """Run the solver for a previously prepared simulation.

        Parameters
        ----------
        sim_id
            UUID returned by :meth:`prepare`.

        Returns
        -------
        float
            Wall-clock solver duration in seconds.

        Raises
        ------
        RunNotFoundError
            If ``sim_id`` does not match a prepared simulation.
        SolverError
            If the solver crashes or fails to converge.
        """
        return self._runner.execute(sim_id)

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations and derived results for a completed simulation.

        Parameters
        ----------
        sim_id
            UUID of the executed simulation.
        extractors
            Optional subset of extractor names. ``None`` runs all registered
            extractors for the workflow.

        Raises
        ------
        RunNotFoundError
            If ``sim_id`` is unknown.
        ExtractError
            If an extractor fails to read the solver outputs.
        """
        return self._runner.ingest(sim_id, extractors=extractors)

    def render(
        self,
        sim_id: str,
        *,
        figures: list[str] | None = None,
    ) -> list[Path]:
        """Render the display figures attached to this simulation.

        Parameters
        ----------
        sim_id
            UUID of the simulation whose figures must be rendered.
        figures
            Optional subset of figure names. ``None`` renders every figure
            declared in the project display config.

        Returns
        -------
        list[pathlib.Path]
            Paths to the rendered figures.

        Raises
        ------
        DisplayError
            If a figure backend fails.
        FigureNotFoundError
            If ``figures`` contains a name unknown to the registry.
        """
        return self._runner.render(sim_id, figures=figures)

    def cleanup(
        self,
        sim_id: str,
        *,
        keep_solver_files: bool = False,
        status: str = "completed",
    ) -> None:
        """Finalize the run status and remove the scratch directory.

        Parameters
        ----------
        sim_id
            UUID of the simulation to finalize.
        keep_solver_files
            If ``True``, preserve raw solver inputs and outputs on disk.
        status
            Final catalog status to record (``"completed"`` or ``"failed"``).

        Raises
        ------
        RunNotFoundError
            If ``sim_id`` is unknown.
        """
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
        """Run one simulation with orchestration specified from Python.

        Parameters
        ----------
        time
            Optional ``(start, end, step)`` tuple overriding the time grid.
        processes
            Optional list of processes to activate (``["flow", ...]`` or
            ``[("flow", "modflownwt")]`` tuples for explicit solver picks).
        name
            Optional run name persisted in the catalog.
        overrides
            Flow parameter overrides applied to the simulation plan.

        Returns
        -------
        Run
            Persisted run view for the newly executed simulation.

        Raises
        ------
        PipelineError
            If a workflow step fails during execution.
        SolverError
            If the solver crashes or fails to converge.
        """
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
        """Run a parameter sweep from one project configuration.

        Parameters
        ----------
        parameters
            Mapping of parameter name to a list of values, or to a dict spec
            consumed by the sweep strategy.
        strategy
            Sweep strategy name (``"enumerate"`` builds the cartesian product).
        name_template
            Python format string used to name each derived run.
        parallel
            Number of worker processes. ``1`` runs sequentially.

        Returns
        -------
        list[Run]
            Persisted run views for every sweep point.

        Raises
        ------
        PipelineError
            If one of the workflow runs fails.
        """
        return self._runner.sweep(
            parameters,
            strategy=strategy,
            name_template=name_template,
            parallel=parallel,
        )

    def __repr__(self) -> str:
        return f"ProjectSession(project={self._project!r})"


__all__ = ["ProjectSession"]
