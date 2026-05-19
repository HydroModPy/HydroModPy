"""High-level Project API for interactive Python usage.

Setup-once, run-many interface that keeps the user-facing session state
(``cfg``, workspace, geographic runtime, loaded data, mesh, catalog) behind a
clean API. The TOML-driven workflow (``hmp run``) is unchanged; this module
provides the **programmatic** equivalent.

``Project`` is intentionally not the execution engine. Ordered execution
and resume live in :mod:`hydromodpy.workflow.runner.Pipeline`.
Both routes use the same ``workflow.steps`` helpers so interactive notebooks
and full pipeline runs do not fork the scientific logic.

The facade is composed of four cohesive helpers:

- :class:`hydromodpy.project.session.ProjectSession`: run-phase orchestrator
  exposed via :meth:`Project.session`. Owns ``simulate``, ``sweep`` and the
  prepared-run primitives (``prepare`` / ``execute`` / ``ingest`` /
  ``render`` / ``cleanup``).
- :class:`hydromodpy.project.runner.ProjectRunner` (``project._runner``):
  internal runner for ``run`` / ``calibrate``.
- :class:`hydromodpy.project.catalog.ProjectCatalog` (``project._catalog``):
  catalog access (``store``, ``runs``, ``data``) and lifecycle (``close``).
- :mod:`hydromodpy.project.phases`: model-phase verbs that mutate the
  project directly (``configure``, ``setup_workspace``, ``build_geographic``,
  ``load_data``, ``build_mesh``).

Workflows that run from a TOML payload but do not benefit from setup-once
state (``overview``, ``mesh``, ``compare``, ``report``) are not methods on
``Project``. Use :mod:`hydromodpy._api` (``hmp.overview``, ``hmp.mesh``,
``hmp.compare``, ``hmp.report``) instead.

Example
-------
::

    import hydromodpy as hmp

    project = hmp.Project("hydromodpy.toml")

    result = project.run(Sy=0.05, K=5e-5, name="baseline")
    wt = result.field("watertable_depth", timestep=12)
    ts = result.timeseries("discharge", station="_catchment")

    # Low-level prepared-run primitives
    session = project.session()
    sim_id = session.prepare(name="probe")
    session.execute(sim_id)

    project.close()
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigMissingError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.project.accessors import ProjectDataAccessor, ProjectRunsAccessor
from hydromodpy.project.catalog import ProjectCatalog
from hydromodpy.project.runner import ProjectRunner, _pin_parent_sim_id
from hydromodpy.project.session import ProjectSession
from hydromodpy.project.state import PROJECT_ATTR_TO_STATE_FIELD, ProjectState

if TYPE_CHECKING:
    from hydromodpy.core.state.data import LoadedDataContext
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.core.time.window import (
        ResolvedSimulationTimeGrid,
        ResolvedSteadySimulationTimeGrid,
    )
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.run import Run
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.spatial.geographic.catchment_delineation import (
        CatchmentDelineation,
    )

logger = get_logger(__name__)


class Project:
    """Setup-once, run-many interface for HydroModPy simulations.

    Builds the geographic/domain/data context once, then allows running
    multiple simulations with parameter overrides.

    Three concerns split the public surface:

    1. **Factory and lifecycle** - constructors (``__init__``, ``lazy``,
       ``from_toml`` / ``from_json`` / ``from_dict``, ``rerun``), context
       manager (``__enter__`` / ``__exit__``), ``close``, ``__repr__`` and
       the inspection / accessor properties (``data``, ``runs``, ``cfg``,
       ``geographic``, ``domain``, ``store``, ``time_grid``,
       ``loaded_data``, ``workflow_context``, ``has_mesh``, ``data_loaded``,
       ``__getitem__``).
    2. **Model phase** - ``setup_workspace``, ``build_geographic``,
       ``rebuild_geographic``, ``load_data``, ``reload_data``,
       ``build_mesh``.
    3. **Run phase** - ``run``, ``calibrate`` and the prepared-run wrapper
       ``session()`` returning a :class:`ProjectSession`.

    TOML-only workflows that do not benefit from setup-once state
    (``overview``, ``mesh``, ``compare``, ``report``) live on
    :mod:`hydromodpy._api`.

    Parameters
    ----------
    config : str, Path, or HydroModPyConfig
        Either a path to a TOML file (``base_config`` inheritance is
        supported) or a fully-built :class:`HydroModPyConfig` instance
        for fully-Python workflows.
    solver : str, optional
        Flow solver name. Auto-detected from the config, defaults to
        ``"modflow_nwt"``.
    headless : bool, optional
        Disable display and postprocess runners (useful for calibration
        loops where generating figures per iteration is wasteful).

    Examples
    --------
    TOML-driven (the CLI path, but usable from Python too)::

        import hydromodpy as hmp

        project = hmp.Project("hydromodpy.toml")
        r = project.run(Sy=0.05)

    Same TOML, orchestration from Python::

        project = hmp.Project("hydromodpy.toml")
        r = project.simulate(
            time=("2000-01-01", "2005-12-31", "1 month"),
            processes=[("flow", "modflow_nwt")],
            Sy=0.05,
        )

    Full Python, no TOML::

        from hydromodpy.config import HydroModPyConfig

        cfg = HydroModPyConfig(...)
        project = hmp.Project(cfg)
        r = project.simulate(
            time=("2000-01-01", "2005-12-31", "1 month"),
            processes=["flow"],
            Sy=0.05,
        )
    """

    def __init__(
        self,
        config: str | Path | object,
        *,
        solver: str | None = None,
        headless: bool = False,
        no_display: bool = False,
        _lazy: bool = False,
    ) -> None:
        """Build a Project from a TOML path or a HydroModPyConfig instance.

        By default the model phase runs eagerly: workspace is created, geographic
        is built, data is loaded, the mesh is generated. Use :meth:`Project.lazy`
        to defer the model phase and drive each verb from Python.
        """
        from hydromodpy.project import phases as project_phases

        object.__setattr__(self, "_state", ProjectState())
        project_phases.configure(
            self,
            config,
            solver=solver,
            headless=headless,
            no_display=no_display,
        )
        object.__setattr__(self, "_runner", ProjectRunner(self))
        object.__setattr__(self, "_catalog", ProjectCatalog(self))
        if not _lazy:
            self.build_geographic()
            self.load_data()
            self.build_mesh()

    def __setattr__(self, name: str, value: Any) -> None:
        """Proxy state-field assignments to :attr:`_state`.

        Names declared in :data:`PROJECT_ATTR_TO_STATE_FIELD` are routed to the
        :class:`ProjectState` container; everything else (``_runner``,
        ``_catalog``, ``_state`` itself) lives directly on the Project instance.
        """
        target = PROJECT_ATTR_TO_STATE_FIELD.get(name)
        state = self.__dict__.get("_state") if target is not None else None
        if target is not None and state is not None:
            object.__setattr__(state, target, value)
            return
        object.__setattr__(self, name, value)

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attribute reads to :attr:`_state` when applicable."""
        target = PROJECT_ATTR_TO_STATE_FIELD.get(name)
        if target is not None:
            state = self.__dict__.get("_state")
            if state is not None:
                return getattr(state, target)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    @classmethod
    def lazy(
        cls,
        config: str | Path | object,
        *,
        solver: str | None = None,
        headless: bool = False,
        no_display: bool = False,
    ) -> Project:
        """Validate ``config`` and build an empty context without running anything.

        The caller drives :meth:`build_geographic`, :meth:`load_data`,
        :meth:`build_mesh` (and optionally :meth:`setup_workspace`) manually.

        Parameters
        ----------
        config
            TOML path or validated configuration object.
        solver
            Optional flow solver override.
        headless
            Disable interactive display side effects.
        no_display
            Skip display generation for later run phases.

        Returns
        -------
        Project
            Project with validated configuration and empty runtime context.

        Raises
        ------
        FileNotFoundError
            If ``config`` is a path that does not exist.
        ConfigValidationError
            If the resolved payload fails Pydantic validation.

        Examples
        --------
        >>> project = Project.lazy("hydromodpy.toml")
        >>> project.build_geographic()
        >>> project.load_data()
        >>> project.build_mesh()
        """
        return cls(
            config,
            solver=solver,
            headless=headless,
            no_display=no_display,
            _lazy=True,
        )

    @classmethod
    def from_toml(cls, config_path: str | Path, **kwargs) -> Project:
        """Build a Project from a TOML path.

        Parameters
        ----------
        config_path
            Path to a HydroModPy TOML file.
        kwargs
            Options forwarded to ``Project``.

        Returns
        -------
        Project
            Project initialized from the TOML file.

        Raises
        ------
        FileNotFoundError
            If ``config_path`` does not exist on disk.
        ConfigValidationError
            If the TOML payload fails Pydantic validation.

        Examples
        --------
        >>> import hydromodpy as hmp
        >>> project = hmp.Project.from_toml("hydromodpy.toml")
        """
        return cls(Path(config_path), **kwargs)

    @classmethod
    def from_json(
        cls,
        payload: str | bytes,
        *,
        base_dir: str | Path | None = None,
        **kwargs,
    ) -> Project:
        """Build a Project from a JSON string.

        Parameters
        ----------
        payload
            JSON payload validated against ``HydroModPyConfig``.
        base_dir
            Base directory used to resolve relative paths in the payload.
        kwargs
            Options forwarded to ``Project``.

        Returns
        -------
        Project
            Project initialized from the validated JSON payload.

        Raises
        ------
        ConfigValidationError
            If the JSON payload fails Pydantic validation.
        json.JSONDecodeError
            If ``payload`` is not valid JSON.
        """
        from hydromodpy.config import HydroModPyConfig

        cfg = HydroModPyConfig.from_json(payload, base_dir=base_dir)
        return cls(cfg, **kwargs)

    @classmethod
    def from_dict(
        cls,
        payload: dict,
        *,
        base_dir: str | Path | None = None,
        **kwargs,
    ) -> Project:
        """Build a Project from a dictionary payload.

        Parameters
        ----------
        payload
            Mapping validated against ``HydroModPyConfig``.
        base_dir
            Base directory used to resolve relative paths in the payload.
        kwargs
            Options forwarded to ``Project``.

        Returns
        -------
        Project
            Project initialized from the validated mapping.

        Raises
        ------
        ConfigValidationError
            If the mapping fails Pydantic validation.
        """
        from hydromodpy.config import HydroModPyConfig

        cfg = HydroModPyConfig.from_dict(payload, base_dir=base_dir)
        return cls(cfg, **kwargs)

    @classmethod
    def rerun(
        cls,
        run: Run,
        *,
        name: str | None = None,
        config_overrides: Mapping[str, Any] | None = None,
        solver: str | None = None,
        headless: bool = False,
        no_display: bool = False,
        **overrides,
    ) -> Run:
        """Launch a new simulation from a persisted run snapshot.

        ``run`` remains a read-only result view; this Project-level helper owns
        the orchestration required to rebuild the configuration, execute the
        workflow, and record the new run with ``parent_sim_id`` pointing to the
        original simulation.

        Parameters
        ----------
        run
            Persisted run to use as the reproducible source snapshot.
        name
            Optional name for the derived run.
        config_overrides
            Deep-merge patch applied to the stored config snapshot. Keys must
            match :class:`HydroModPyConfig` top-level fields; the merged
            payload is validated by Pydantic, so unknown keys raise.
        solver, headless, no_display
            Options forwarded to the derived :class:`Project`.
        overrides
            Flow parameter overrides forwarded to :meth:`Project.run`.

        Returns
        -------
        Run
            Persisted run view for the derived simulation.

        Raises
        ------
        ConfigMissingError
            If ``run`` has no persisted config snapshot.
        PipelineError
            If the derived pipeline produces no new Run, e.g. ``dry_run`` mode.
        """
        snapshot = run.config_snapshot
        if snapshot is None:
            raise ConfigMissingError(
                f"Simulation '{run.sim_id}' has no config snapshot - cannot rerun"
            )

        from hydromodpy.config import HydroModPyConfig

        cfg = HydroModPyConfig.from_snapshot(snapshot, **(config_overrides or {}))
        project = cls(
            cfg,
            solver=solver,
            headless=headless,
            no_display=no_display,
        )
        with _pin_parent_sim_id(project._ctx, run.sim_id):
            new_run = project._runner.run(name=name, **overrides)
        if new_run is None:
            raise PipelineError(
                f"rerun of '{run.sim_id}' did not produce a new Run "
                "(dry_run or short-circuited workflow)."
            )
        return new_run

    # -- Model-phase verbs (delegate to project_phases) -------------------

    def setup_workspace(self) -> None:
        """Bootstrap shared runtime state for the project session.

        This Project-level verb prepares the workspace/catalog anchor and the
        shared geographic/domain/process objects used by later data, mesh, and
        solver phases. It is not a standalone Pipeline step; Pipeline runs get
        the same setup through ``BuildGeographicStep``.
        """
        from hydromodpy.project import phases as project_phases

        project_phases.setup_workspace(self)

    def build_geographic(self, *, reuse_dem: bool = False) -> None:
        """Mark geographic/domain runtime ready and invalidate downstream state."""
        from hydromodpy.project import phases as project_phases

        project_phases.build_geographic(self, reuse_dem=reuse_dem)

    def load_data(self, *, types: list[str] | None = None) -> None:
        """Load the external forcings declared in [data]."""
        from hydromodpy.project import phases as project_phases

        project_phases.load_data(self, types=types)

    def reload_data(self, *, types: list[str]) -> None:
        """Reload a subset of data variables without touching the others."""
        from hydromodpy.project import phases as project_phases

        project_phases.reload_data(self, types=types)

    def rebuild_geographic(self, *, reuse_dem: bool = False) -> None:
        """Rerun the geographic pipeline and invalidate the mesh."""
        from hydromodpy.project import phases as project_phases

        project_phases.rebuild_geographic(self, reuse_dem=reuse_dem)

    def build_mesh(self, **overrides) -> None:
        """Build the catchment mesh from the current geographic context."""
        from hydromodpy.project import phases as project_phases

        project_phases.build_mesh(self, **overrides)

    # -- Inspection properties --------------------------------------------

    @property
    def has_mesh(self) -> bool:
        """True once the mesh has been built for the project."""
        return self._ctx.setup.mesh_planar is not None

    @property
    def data_loaded(self) -> set[str]:
        """Set of data types already loaded for this project."""
        return self._catalog.data_loaded

    @property
    def data(self) -> ProjectDataAccessor:
        """Accessor for the input-data cache scoped to this project."""
        return self._catalog.data

    @property
    def runs(self) -> ProjectRunsAccessor:
        """Accessor for the simulation catalog scoped to this project."""
        return self._catalog.runs

    def __getitem__(self, sim_id: str) -> Run:
        """Return the Run view associated with ``sim_id``."""
        return self._catalog.get(sim_id)

    # -- Public properties (context state) --------------------------------

    @property
    def geographic(self) -> CatchmentDelineation | None:
        """Geographic runtime object (DEM, watershed, CRS)."""
        return self._ctx.setup.geographic

    @property
    def domain(self) -> Domain | None:
        """Spatial domain (mesh, layers, zones)."""
        return self._ctx.setup.domain

    @property
    def store(self) -> SimulationCatalog | None:
        """Open SimulationCatalog for direct queries across all runs."""
        return self._catalog.store

    @property
    def time_grid(
        self,
    ) -> ResolvedSimulationTimeGrid | ResolvedSteadySimulationTimeGrid | None:
        """Resolved simulation time grid."""
        return self._time_grid

    @property
    def loaded_data(self) -> LoadedDataContext:
        """Loaded data context (recharge, geology, hydrometry, etc.)."""
        return self._ctx.loaded_data

    @property
    def workflow_context(self) -> WorkflowContext:
        """Mutable workflow runtime state threaded through workflow steps."""
        return self._ctx

    # -- Run-phase session ------------------------------------------------

    def session(self) -> ProjectSession:
        """Return the run-phase orchestration facade bound to this project.

        ``session`` exposes the prepared-run primitives (``prepare``,
        ``execute``, ``ingest``, ``render``, ``cleanup``) plus ``simulate``
        and ``sweep``. The high-level verbs ``run`` and ``calibrate`` remain
        on :class:`Project` for the common case.
        """
        return ProjectSession(self)

    # -- Run-phase API (delegates to ProjectRunner) -----------------------

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
        """Run the configured workflow and return its result.

        Single entry point that unifies the interactive Python flow and the
        ``hmp run`` CLI. Flow parameter overrides (``Sy``, ``K``, ``Ss``) and
        the special keys ``thickness``, ``first_clim``, ``properties`` are
        applied to the plan before the Pipeline runs.

        Parameters
        ----------
        name
            Optional run name persisted in the catalog.
        resume
            Existing run identifier to resume from the workflow journal.
        from_step, until_step
            Optional step bounds for partial workflow execution.
        dry_run
            Build and validate the workflow without executing solver work.
        frozen
            Require frozen input-data references.
        no_display
            Skip display rendering for this run.
        overrides
            Parameter overrides applied to the simulation plan.

        Returns
        -------
        Run or None
            Persisted run view for simulation workflows. Dry runs and some
            non-simulation workflows may return ``None``.

        Raises
        ------
        PipelineError
            If a workflow step fails during execution.
        SolverError
            If the configured solver crashes or fails to converge.
        ResumeError
            If ``resume`` references an incompatible journal state.

        Examples
        --------
        >>> run = project.run(Sy=0.05, name="probe")
        >>> run.summary()

        See Also
        --------
        hydromodpy.run
            Functional facade for one-off TOML execution.
        hydromodpy.results.run.Run
            Per-simulation result view returned by successful runs.
        """
        return self._runner.run(
            name=name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            dry_run=dry_run,
            frozen=frozen,
            no_display=no_display,
            **overrides,
        )

    def calibrate(
        self,
        *,
        config_path: str | Path | None = None,
        parameters: dict[str, dict] | None = None,
        outputs: dict[str, dict] | None = None,
        objective_blocks: list[dict] | None = None,
        method: str | None = None,
        max_iter: int | None = None,
        save_runs: str | None = None,
        seed: int | None = None,
        **kwargs,
    ):
        """Run a calibration campaign on this project.

        Two modes are supported:

        * TOML mode (``config_path`` supplied): delegate to
          ``run_calibration_cli`` with the given TOML path. Extra keyword
          arguments are forwarded.
        * Python mode (``parameters`` supplied): build a
          :class:`CalibrationConfig` in memory from the declarations and
          run the same loop.

        Parameters
        ----------
        config_path
            Calibration TOML path for TOML mode.
        parameters
            Python-mode parameter declarations.
        outputs
            Python-mode output declarations.
        objective_blocks
            Python-mode objective block declarations.
        method
            Optimizer method name.
        max_iter
            Maximum number of optimizer iterations.
        save_runs
            Policy controlling which trial runs remain persisted.
        seed
            Optional optimizer seed.
        kwargs
            Extra options forwarded to the calibration runner.

        Returns
        -------
        CalibrationReport or Any
            Structured calibration report when ``return_report`` is true,
            otherwise the runner-specific result.

        Raises
        ------
        ConfigMissingError
            Raised when neither ``config_path`` nor ``parameters`` is supplied.
        """
        from hydromodpy.core.exceptions import ConfigMissingError

        if config_path is not None:
            from hydromodpy.calibration.runner import run_calibration_cli

            return run_calibration_cli(Path(config_path).expanduser().resolve(), **kwargs)

        if not parameters:
            raise ConfigMissingError(
                "Project.calibrate() requires either config_path= or "
                "parameters= (Python-mode declaration)."
            )

        from hydromodpy.calibration.config import CalibrationConfig
        from hydromodpy.calibration.runner import run_calibration_programmatic

        payload: dict[str, object] = {}
        if method is not None:
            payload["method"] = method
        if max_iter is not None:
            payload["max_iter"] = max_iter
        if save_runs is not None:
            payload["save_runs"] = save_runs
        if seed is not None:
            payload["seed"] = seed
        payload["parameters"] = dict(parameters)
        if outputs is not None:
            payload["outputs"] = dict(outputs)
        if objective_blocks is not None:
            payload["objective_blocks"] = list(objective_blocks)
        payload.update(
            {
                key: value
                for key, value in kwargs.items()
                if key
                not in {
                    "workspace",
                    "project",
                    "project_label",
                    "metric_fn",
                    "objective",
                    "return_report",
                }
            }
        )

        cfg = CalibrationConfig.model_validate(payload)
        return run_calibration_programmatic(
            cfg,
            project=self,
            workspace=kwargs.get("workspace"),
            project_label=kwargs.get("project_label", kwargs.get("project", "calibration")),
            metric_fn=kwargs.get("metric_fn"),
            objective=kwargs.get("objective"),
            return_report=kwargs.get("return_report", True),
        )

    # -- Lifecycle --------------------------------------------------------

    def close(self) -> None:
        """Close the SimulationCatalog and clean up preprocessing files."""
        self._catalog.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self) -> str:
        source = self._config_path.name if self._config_path else "<in-memory>"
        return f"Project({source!r})"

    def _repr_html_(self) -> str:
        if self._config_path is not None:
            source_label = self._config_path.name
            project_name = self._config_path.parent.name
        else:
            source_label = "&lt;in-memory&gt;"
            project_name = getattr(self, "_project_name", "") or "&mdash;"
        runs = self._run_history
        n_runs = len(runs)
        last_run = runs[-1] if runs else None
        rows: list[tuple[str, str]] = [
            ("config", f"<code>{source_label}</code>"),
            ("project", project_name),
            ("solver", str(getattr(self, "_solver", "") or "&mdash;")),
            ("headless", "yes" if getattr(self, "_headless", False) else "no"),
            ("runs", str(n_runs)),
            (
                "last run",
                f"<code>{last_run.sim_id[:8]}</code> ({last_run.name})"
                if last_run is not None
                else "&mdash;",
            ),
        ]
        body = "".join(
            f"<tr><th style='text-align:left;padding-right:8px'>{k}</th><td>{v}</td></tr>"
            for k, v in rows
        )
        return (
            "<div><b>Project</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
