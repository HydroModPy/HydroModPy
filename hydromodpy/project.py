"""High-level Project API for interactive Python usage.

Setup-once, run-many interface that wraps the launcher's internal phases
behind a clean API. The TOML-driven workflow (``hmp run``) is unchanged;
this module provides the **programmatic** equivalent.

The facade is composed of three cohesive helpers:

- :class:`hydromodpy.project_runner.ProjectRunner` (``project._runner``):
  the heavy run-phase methods (``run``, ``simulate``, ``sweep``,
  ``calibrate``, ``mesh``, ``report``, prepared-run primitives).
- :class:`hydromodpy.project_catalog.ProjectCatalog` (``project._catalog``):
  catalog access (``store``, ``runs``, ``data``) and lifecycle (``close``).
- :mod:`hydromodpy.project_phases`: model-phase verbs that mutate the
  project directly (``configure``, ``setup_workspace``, ``build_geographic``,
  ``load_data``, ``build_mesh``).

Example
-------
::

    import hydromodpy as hmp

    project = hmp.Project("project.toml")

    result = project.run(Sy=0.05, K=5e-5, name="baseline")
    wt = result.field("watertable_depth", timestep=12)
    ts = result.timeseries("discharge", station="_catchment")

    project.close()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.project_accessors import ProjectDataAccessor, ProjectRunsAccessor
from hydromodpy.project_catalog import ProjectCatalog
from hydromodpy.project_runner import ProjectRunner

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

    Parameters
    ----------
    config : str, Path, or HydroModPyConfig
        Either a path to a TOML file (``base_config`` inheritance is
        supported) or a fully-built :class:`HydroModPyConfig` instance
        for fully-Python workflows.
    solver : str, optional
        Flow solver name. Auto-detected from the config, defaults to
        ``"modflownwt"``.
    headless : bool, optional
        Disable display and postprocess runners (useful for calibration
        loops where generating figures per iteration is wasteful).

    Examples
    --------
    TOML-driven (the CLI path, but usable from Python too)::

        import hydromodpy as hmp

        project = hmp.Project("project.toml")
        r = project.run(Sy=0.05)

    Same TOML, orchestration from Python::

        project = hmp.Project("project.toml")
        r = project.simulate(
            time=("2000-01-01", "2005-12-31", "1 month"),
            processes=[("flow", "modflownwt")],
            Sy=0.05,
        )

    Full Python, no TOML::

        from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

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
        from hydromodpy import project_phases

        project_phases.configure(
            self,
            config,
            solver=solver,
            headless=headless,
            no_display=no_display,
        )
        self._runner = ProjectRunner(self)
        self._catalog = ProjectCatalog(self)
        if not _lazy:
            self.build_geographic()
            self.load_data()
            self.build_mesh()

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
        """
        return cls(
            config,
            solver=solver,
            headless=headless,
            no_display=no_display,
            _lazy=True,
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path, **kwargs) -> Project:
        """Build a Project from a TOML configuration file."""
        return cls(toml_path, **kwargs)

    @classmethod
    def from_json(
        cls,
        payload: str | bytes,
        *,
        base_dir: str | Path | None = None,
        **kwargs,
    ) -> Project:
        """Build a Project from a JSON string validated against HydroModPyConfig."""
        from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

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
        """Build a Project from a dict payload validated against HydroModPyConfig."""
        from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

        cfg = HydroModPyConfig.from_dict(payload, base_dir=base_dir)
        return cls(cfg, **kwargs)

    # -- Model-phase verbs (delegate to project_phases) -------------------

    def setup_workspace(self) -> None:
        """Materialize the workspace and structural objects (Domain, Flow, Transport)."""
        from hydromodpy import project_phases

        project_phases.setup_workspace(self)

    def build_geographic(self, *, reuse_dem: bool = False) -> None:
        """Build the geographic runtime (DEM, watershed, topography)."""
        from hydromodpy import project_phases

        project_phases.build_geographic(self, reuse_dem=reuse_dem)

    def load_data(self, *, types: list[str] | None = None) -> None:
        """Load the external forcings declared in [data]."""
        from hydromodpy import project_phases

        project_phases.load_data(self, types=types)

    def reload_data(self, *, types: list[str]) -> None:
        """Reload a subset of data variables without touching the others."""
        from hydromodpy import project_phases

        project_phases.reload_data(self, types=types)

    def rebuild_geographic(self, *, reuse_dem: bool = False) -> None:
        """Rerun the geographic pipeline and invalidate the mesh."""
        from hydromodpy import project_phases

        project_phases.rebuild_geographic(self, reuse_dem=reuse_dem)

    def build_mesh(self, **overrides) -> None:
        """Build the catchment mesh from the current geographic context."""
        from hydromodpy import project_phases

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

    # -- Run-phase API (delegates to ProjectRunner) -----------------------

    def prepare(self, *, name: str | None = None, **overrides) -> str:
        """Reserve a sim_id, register the simulation and persist all inputs."""
        return self._runner.prepare(name=name, **overrides)

    def execute(self, sim_id: str) -> float:
        """Run the solver for a previously prepared simulation."""
        return self._runner.execute(sim_id)

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations for a completed simulation."""
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

    def run(
        self,
        *,
        name: str | None = None,
        checkpoint: bool = True,
        resume: str | None = None,
        from_step: str | int | None = None,
        until_step: str | int | None = None,
        dry_run: bool = False,
        frozen: bool = False,
        no_display: bool = False,
        **overrides,
    ) -> Run | None:
        """Run the simulation through the canonical workflow Pipeline.

        Single entry point that unifies the interactive Python flow and the
        ``hmp run`` CLI. Flow parameter overrides (``Sy``, ``K``, ``Ss``) and
        the special keys ``thickness``, ``first_clim``, ``properties`` are
        applied to the plan before the Pipeline runs.
        """
        return self._runner.run(
            name=name,
            checkpoint=checkpoint,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            dry_run=dry_run,
            frozen=frozen,
            no_display=no_display,
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
        """Run N simulations from a parameter table."""
        return self._runner.sweep(
            parameters,
            strategy=strategy,
            name_template=name_template,
            parallel=parallel,
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

        * **TOML mode** (``config_path`` supplied): delegate to
          :func:`hydromodpy.calibration.runner.run_calibration_cli` with the
          given TOML path.
        * **Python mode** (``parameters`` supplied): build a
          :class:`CalibrationConfig` in memory from the declarations and
          run the same loop.
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

    def mesh(self) -> dict:
        """Run the standalone mesh-only workflow defined by this project."""
        return self._runner.mesh()

    def report(self, session_id: str | None = None) -> Path:
        """Render the HTML report for a calibration session."""
        return self._runner.report(session_id)

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
