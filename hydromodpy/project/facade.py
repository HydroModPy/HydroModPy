"""High-level Project API for interactive Python usage.

Construct cheap, simulate many. ``Project(config)`` only validates the config;
the heavy model phase (geographic delineation, data download, mesh) runs lazily
on the first :meth:`Project.simulate` (or the first access to a runtime
accessor), or eagerly via :meth:`Project.prepare` / the per-phase verbs. The
TOML-driven workflow (``hmp run``) is unchanged; this module is its
**programmatic** equivalent.

``Project`` is intentionally not the execution engine. Ordered execution and
resume live in :mod:`hydromodpy.workflow.runner.Pipeline`. Both routes use the
same ``workflow.steps`` helpers so interactive notebooks and full pipeline runs
do not fork the scientific logic.

The facade is composed of three cohesive helpers:

- :class:`hydromodpy.project.runner.ProjectRunner` (``project._runner``):
  internal runner backing ``simulate`` / ``calibrate``.
- :class:`hydromodpy.project.catalog.ProjectCatalog` (``project._catalog``):
  catalog access (``store``, ``runs``, ``data``) and lifecycle (``close``).
- :mod:`hydromodpy.project.phases`: model-phase verbs that mutate the
  project directly (``configure``, ``setup_workspace``, ``build_geographic``,
  ``load_data``, ``build_mesh``).
- :mod:`hydromodpy.project.accessors`: the reads of a project directory
  (``cases``, ``sites``, ``best``, ``runs``, ``sessions``).

A project is also opened on its directory, read only, by ``hmp.open``
(:func:`open_project`). It then reads its plan, its runs and its sessions
from the disk, and launches its cases with the words of ``hmp project``:
``plan``, ``run``, ``status``, ``collect``, ``publish``. Its configuration is
read from ``project.toml`` only when a model verb needs it.

Example
-------
::

    import hydromodpy as hmp

    project = hmp.Project("project.toml")  # cheap: validates config
    run = project.simulate(Sy=0.05, K=5e-5, name="baseline")  # builds, then runs
    wt = run.field("watertable_depth", timestep=12)

    # Parameter sweep: one simulate() per value
    for sy in (0.01, 0.05, 0.1):
        project.simulate(name=f"sy_{sy}", Sy=sy)

    project.close()

    proj = hmp.open("projects/bretagne_k")  # a [sites] project, read only
    proj.cases  # the plan joined to the outcomes
    proj.best("nse", by="site")  # the best calibrated run of each site
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hydromodpy.core.exceptions import ConfigMissingError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    PROJECT_MARKER_FILENAME,
    resolve_project_root,
    run_scratch,
    summary_dir_for,
)
from hydromodpy.project.accessors import (
    BEST_LABEL,
    ProjectDataAccessor,
    ProjectRunsAccessor,
    ProjectSessions,
    best_frame,
    cases_frame,
    sites_frame,
)
from hydromodpy.project.catalog import ProjectCatalog
from hydromodpy.project.runner import ProjectRunner, _pin_parent_sim_id, scratch_of_resumed_run
from hydromodpy.project.state import (
    CONFIGURED_STATE_FIELDS,
    PROJECT_ATTR_TO_STATE_FIELD,
    ProjectState,
)

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd

    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.config.sites.expansion import PlanDraft
    from hydromodpy.core.state.data import LoadedDataContext
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.core.time.window import (
        ResolvedSimulationTimeGrid,
        ResolvedSteadySimulationTimeGrid,
    )
    from hydromodpy.project.attempt import SealedRun
    from hydromodpy.project.launch import LaunchReport, StatusReport
    from hydromodpy.project.spinup import SpinupResult
    from hydromodpy.project.summary import SummaryPaths
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.checks import CalibratedBy
    from hydromodpy.results.lineage import Lineage
    from hydromodpy.results.publication import PublicationExtra, PublicationFormat
    from hydromodpy.results.run import Run
    from hydromodpy.simulation.spinup_config import SpinupConfig
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.spatial.geographic.catchment_delineation import (
        CatchmentDelineation,
    )

logger = get_logger(__name__)


def _resolve_config(config: str | Path | object | dict) -> object:
    """Normalize a polymorphic config input to a path or ``HydroModPyConfig``.

    ``dict`` -> validated config; JSON string (starts with ``{``) -> validated
    config; a TOML path or an already-built config object passes through.
    """
    if isinstance(config, Mapping):
        from hydromodpy.config import HydroModPyConfig

        return HydroModPyConfig.from_dict(dict(config))
    if isinstance(config, str) and config.lstrip().startswith("{"):
        from hydromodpy.config import HydroModPyConfig

        return HydroModPyConfig.from_json(config)
    return config


class Project:
    """Setup-once, run-many interface for HydroModPy simulations.

    ``Project(config)`` is cheap: it validates the configuration and builds an
    empty runtime context. The heavy model phase (geographic, data, mesh) is
    built lazily on the first :meth:`simulate` (or eagerly via :meth:`prepare`
    or the per-phase verbs ``build_geographic`` / ``load_data`` /
    ``build_mesh``). Run many simulations with parameter overrides; inspect
    past runs through :attr:`runs` and inputs through :attr:`data`.

    Parameters
    ----------
    config : str, Path, HydroModPyConfig, dict, or JSON str
        A TOML path, a fully-built :class:`HydroModPyConfig`, a ``dict``
        payload, or a JSON string (auto-detected).
    solver : str, optional
        Flow solver name. Auto-detected from the config, defaults to
        ``"modflow_nwt"``.
    headless : bool, optional
        Disable display and postprocess runners (useful for calibration
        loops where generating figures per iteration is wasteful).
    no_display : bool, optional
        Skip display generation for later run phases.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> project = hmp.Project("project.toml")  # doctest: +SKIP
    >>> run = project.simulate(Sy=0.05)  # doctest: +SKIP
    >>> project.close()  # doctest: +SKIP
    """

    def __init__(
        self,
        config: str | Path | object | dict,
        *,
        solver: str | None = None,
        headless: bool = False,
        no_display: bool = False,
    ) -> None:
        """Validate ``config`` and build an empty runtime context (cheap).

        No heavy I/O: geographic delineation, data download and meshing are
        deferred to the first :meth:`simulate` (or :meth:`prepare`).
        """
        from hydromodpy.project import phases as project_phases

        object.__setattr__(self, "_state", ProjectState())
        project_phases.configure(
            self,
            _resolve_config(config),
            solver=solver,
            headless=headless,
            no_display=no_display,
        )
        object.__setattr__(self, "_runner", ProjectRunner(self))
        object.__setattr__(self, "_catalog", ProjectCatalog(self))

    def _ensure_model_built(self) -> None:
        """Build the model phase once, lazily, on first run or accessor use.

        Only an untouched Project is built here. A phase marker that already
        names a step means something built it - the facade verbs, or a run
        bounded before ``setup_process`` - and the Pipeline completes what is
        missing through ``is_prebuilt``. Completing it here instead would make
        ``reload_data``, which moves the marker back to ``"data"`` on purpose,
        regenerate a mesh that Gmsh does not reproduce run to run.
        """
        if self._phase == "uninitialized":
            self.build_geographic()
            self.load_data()
            self.build_mesh()

    def prepare(self) -> Project:
        """Eagerly build the model phase (geographic, data, mesh). Returns self."""
        self._ensure_model_built()
        return self

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
        """Forward unknown attribute reads to :attr:`_state` when applicable.

        A project opened on its directory configures itself on the first read
        of a field only a configuration fills (:data:`CONFIGURED_STATE_FIELDS`).
        """
        target = PROJECT_ATTR_TO_STATE_FIELD.get(name)
        if target is not None:
            state = self.__dict__.get("_state")
            if state is not None:
                if target in CONFIGURED_STATE_FIELDS and state.cfg is None and state.root:
                    self._configure_opened()
                return getattr(state, target)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def _configure_opened(self) -> None:
        """Configure a project opened on its directory from its ``project.toml``.

        A ``[sites]`` project has one configuration per case, written by its
        plan; it is read and launched, never configured as one model.
        """
        from hydromodpy.config.sites.expansion import SitesProjectError, find_sites_file
        from hydromodpy.core.toml_io.loader import read_toml_chain
        from hydromodpy.project import phases as project_phases

        state = self.__dict__["_state"]
        marker = state.root / PROJECT_MARKER_FILENAME
        if not marker.is_file():
            raise ConfigMissingError(
                f"{state.root} holds no {PROJECT_MARKER_FILENAME}: an opened project builds "
                "its model from it. Open a configuration with hmp.Project(<file>.toml)."
            )
        if find_sites_file(read_toml_chain(marker)) is not None:
            raise SitesProjectError(
                f"{marker} is a [sites] project: each case is configured by its plan. Read "
                "it with proj.cases, launch it with proj.run(), or build one case with "
                "hmp.Project('plan/<hash>/<case>.toml')."
            )
        try:
            project_phases.configure(self, marker, solver=None, headless=False, no_display=False)
        except BaseException:
            state.cfg = None
            raise

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
            Flow parameter overrides forwarded to :meth:`Project.simulate`.

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

    # -- Public config view -----------------------------------------------

    @property
    def config(self) -> HydroModPyConfig:
        """Validated configuration driving this project (read-only)."""
        return self._cfg

    # -- Inspection properties --------------------------------------------

    @property
    def has_mesh(self) -> bool:
        """True once the mesh has been built for the project."""
        return self._ctx.setup.cell_mesh is not None

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
        """The runs of this project: call it for a RunSet, ``runs(site="J0014010")``.

        Reads the index, refreshed from the run directories; builds nothing.
        """
        self._index()
        return self._catalog.runs

    def __getitem__(self, ref: str) -> Run:
        """Return the run a reference names: a case, a run name, an id, ``runs/<name>``."""
        return self._index()[ref]

    # -- Public properties (context state) --------------------------------

    @property
    def geographic(self) -> CatchmentDelineation | None:
        """Geographic runtime object (DEM, watershed, CRS). Triggers build."""
        self._ensure_model_built()
        return self._ctx.setup.geographic

    @property
    def domain(self) -> Domain | None:
        """Spatial domain (mesh, layers, zones). Triggers build."""
        self._ensure_model_built()
        return self._ctx.setup.domain

    @property
    def store(self) -> Catalog:
        """The index of this project, refreshed from the run directories, read only."""
        return self._index()

    @property
    def time_grid(
        self,
    ) -> ResolvedSimulationTimeGrid | ResolvedSteadySimulationTimeGrid | None:
        """Resolved simulation time grid."""
        return self._time_grid

    @property
    def loaded_data(self) -> LoadedDataContext:
        """Loaded data context (recharge, geology, hydrometry, etc.). Triggers build."""
        self._ensure_model_built()
        return self._ctx.loaded_data

    @property
    def workflow_context(self) -> WorkflowContext:
        """Mutable workflow runtime state threaded through workflow steps."""
        return self._ctx

    # -- Project directory: reads and launch (hmp project) -----------------

    @property
    def root(self) -> Path:
        """The project directory, the folder of ``project.toml``."""
        root = self._state.root
        if root is not None:
            return root
        return Path(self._cfg.workspace.project_root).expanduser().resolve()

    def _index(self) -> Catalog:
        """Bring the index up to date with the run directories and return it, open.

        The index is derived from the disk: a pass that finds nothing new
        writes nothing and keeps the open handle.
        """
        from hydromodpy.results.catalog import Catalog
        from hydromodpy.results.catalog.indexer import index_new_runs

        root = self.root
        report = index_new_runs(root)
        store = self._store
        if store is not None and not store.closed and report.unchanged:
            return store
        if store is not None:
            store.close()
        self._store = Catalog(root)
        return self._store

    @property
    def cases(self) -> pd.DataFrame:
        """The cases of the project: the plan joined to the outcomes, one row each.

        Status (planned, invalid, skipped, stale_plan for a case of the plan
        that has no directory; running, completed, partial, failed, aborted,
        stale for one that has), label, headline metric with its window, and
        one column per global parameter.
        """
        return cases_frame(self._index(), self.root)

    @property
    def sites(self) -> gpd.GeoDataFrame:
        """The sites of the project, one row each, with the outlet as a point."""
        return sites_frame(self._index(), self.root)

    @property
    def sessions(self) -> ProjectSessions:
        """The calibration sessions of the project, by directory name."""
        return ProjectSessions(self.root)

    def best(
        self,
        metric: str = "nse",
        *,
        by: Literal["site", "recipe"] | None = "site",
        label: str | None = BEST_LABEL,
        mixed_windows: bool = False,
    ) -> pd.DataFrame:
        """Return the best completed run of each site, one row each.

        The metric is read at the gauge of each run, in the window of its
        rule; best follows its direction. The calibrated runs are ranked by
        default; ``label=None`` ranks every completed run. ``by=None`` gives
        the single best run of the project. A site of completed runs left
        out is named once in a warning, with why: no run scored (declare
        ``[metrics] window``), or none of ``label``.

        Returns
        -------
        pandas.DataFrame
            ``site`` (or ``recipe``), ``case_id``, ``rel_dir``, ``sim_id``,
            ``label``, the global parameters (``K`` ...), the metric under
            its own name, ``station``, ``nse_window_start``, ``nse_window_end``.

        Examples
        --------
        >>> proj = hmp.open("projects/bretagne_k")  # doctest: +SKIP
        >>> proj.best("nse", by="site")  # doctest: +SKIP
        """
        return best_frame(self._index(), metric, by=by, label=label, mixed_windows=mixed_windows)

    def plan(
        self, *, set_overrides: Mapping[str, Any] | None = None, force: bool = False
    ) -> PlanDraft:
        """Resolve the cases of a ``[sites]`` project and write ``plan/<hash>/``.

        The words of ``hmp project plan``. A plan is not rewritten while one
        of its cases runs, unless ``force``.
        """
        from hydromodpy.project.launch import plan_project

        return plan_project(self.root, set_overrides=set_overrides, force=force)

    def run(
        self,
        *,
        parallel: int | None = None,
        only: str | Sequence[str] = (),
        site: str | None = None,
        until: str | None = None,
        fresh: bool = False,
        force: bool = False,
        resume: bool = False,
        prepare_parallel: int | None = None,
    ) -> LaunchReport:
        """Launch the cases of the plan, one process per case.

        The words of ``hmp run project.toml``: ``only`` keeps the cases in
        those states (``"failed"``, ``("failed", "stale")``), ``site`` the
        cases of one site, ``until="data"`` stops after the data phase.
        ``parallel`` is the budget of solves side by side; a calibration case
        counts its own ``[calibration] parallel``.
        """
        from hydromodpy.project.launch import run_plan

        states = (only,) if isinstance(only, str) else tuple(only)
        report = run_plan(
            self.root,
            parallel=parallel,
            prepare_parallel=prepare_parallel,
            only=states,
            site=site,
            until=until,
            fresh=fresh,
            force=force,
            resume=resume,
        )
        self._index()
        return report

    def status(self) -> StatusReport:
        """Return where each case of the plan stands, read from the disk."""
        from hydromodpy.project.launch import project_status

        return project_status(self.root)

    def collect(self, *, write_sites: bool = False, mixed_windows: bool = False) -> SummaryPaths:
        """Write ``summary/``: one table per case and per site, figures, report, README.

        The words of ``hmp project collect``.
        """
        from hydromodpy.project.summary import collect_project

        return collect_project(self.root, write_sites=write_sites, mixed_windows=mixed_windows)

    def publish(
        self,
        to: str | Path,
        *,
        format: PublicationFormat = "dir",
        with_: Sequence[PublicationExtra] = (),
        public: bool = False,
    ) -> Path:
        """Copy ``summary/`` out of the tree, for a reader without HydroModPy.

        The words of ``hmp publish . --to DEST``. Returns the copy. Raises
        ``FileNotFoundError`` before :meth:`collect` wrote ``summary/``.
        """
        from hydromodpy.results.export.publish import publish

        summary = summary_dir_for(self.root)
        if not summary.is_dir():
            raise FileNotFoundError(
                f"{summary} does not exist: write it with proj.collect() before publishing"
            )
        return publish(
            summary, to, project_root=self.root, format=format, with_=with_, public=public
        )

    # -- Run-phase API (delegates to ProjectRunner) -----------------------

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
        lineage: Lineage | None = None,
        calibrated_by: CalibratedBy | None = None,
        **overrides,
    ) -> SealedRun | None:
        """Run one attempt of the case and return what its directory says.

        The worker verb: it claims ``runs/<case>/``, runs the Pipeline, seals
        the run and closes its outcome, and never opens the index of the
        project. ``hmp run`` stops here and indexes afterwards. The keywords
        are those of :meth:`simulate`, plus ``lineage`` and ``calibrated_by``,
        the blocks a promotion or a rerun seals its run with.
        """
        label = name or resume or self.config.simulation.name or "run"
        project_root = Path(self.config.workspace.project_root)
        resumes = scratch_of_resumed_run(project_root, resume) if resume is not None else None
        with run_scratch(project_root, label, resumes=resumes):
            return self._runner.execute(
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

    def simulate(
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
        lineage: Lineage | None = None,
        calibrated_by: CalibratedBy | None = None,
        **overrides,
    ) -> Run | None:
        """Run one simulation through the configured workflow and return its result.

        Builds the model phase on first call (lazy), then runs the Pipeline.
        A run bounded by ``until_step`` before ``setup_process`` needs no shared
        model phase: it executes its own steps and builds nothing else, which is
        how a catchment is delineated without loading data or meshing.
        Flow parameter overrides (``Sy``, ``K``, ``Ss``) and the special keys
        ``thickness``, ``first_clim``, ``properties`` are applied to the plan
        before the Pipeline runs. Call once per point to sweep a parameter.
        Once the attempt is closed, the index of the project is refreshed from
        the run directory and the :class:`Run` view is returned.

        Parameters
        ----------
        name
            Run name, the case the directory is named after. Defaults to
            ``[simulation] name`` of the configuration, and to ``run_0001``,
            ``run_0002``... only when the configuration names no run.
        resume
            Name of an interrupted case to continue in place from its journal.
        from_step, until_step
            Optional step bounds for partial workflow execution. A step name,
            a class name, or an index inside the pipeline.
        dry_run
            Build and validate the workflow without executing solver work.
        frozen
            Require frozen input-data references.
        no_display
            Skip display rendering for this run.
        fresh
            File everything a previous attempt left under ``attempts/<k>/``
            and start the case over.
        force
            Claim a stale case whose process cannot be proven dead.
        lineage, calibrated_by
            The lineage block and the promoting session the run is sealed
            with; a promotion or a rerun passes them.
        overrides
            Parameter overrides applied to the simulation plan.

        Returns
        -------
        Run or None
            Persisted run view for simulation workflows. Dry runs and
            head-only windows return ``None``.

        Raises
        ------
        PipelineError
            If a workflow step fails during execution.
        SolverError
            If the configured solver crashes or fails to converge.
        ResumeError
            If ``resume`` references an incompatible journal state.
        ConfigError
            If ``from_step`` or ``until_step`` names no pipeline step.

        Examples
        --------
        >>> run = project.simulate(Sy=0.05, name="probe")  # doctest: +SKIP
        >>> run.label()  # doctest: +SKIP

        See Also
        --------
        hydromodpy.run
            Functional facade for one-off TOML execution.
        hydromodpy.results.run.Run
            Per-simulation result view returned by successful runs.
        """
        label = name or resume or self.config.simulation.name or "run"
        project_root = Path(self.config.workspace.project_root)
        resumes = scratch_of_resumed_run(project_root, resume) if resume is not None else None
        with run_scratch(project_root, label, resumes=resumes):
            return self._runner.run(
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

    def calibrate(
        self,
        *,
        config_path: str | Path | None = None,
        parameters: dict[str, dict] | None = None,
        outputs: dict[str, dict] | None = None,
        objective_blocks: list[dict] | None = None,
        phases: list[dict] | None = None,
        method: str | None = None,
        max_iter: int | None = None,
        save_runs: str | None = None,
        seed: int | None = None,
        phase: str | None = None,
        **kwargs,
    ):
        """Run a calibration campaign on this project.

        Three modes are supported:

        * TOML mode (``config_path`` supplied): delegate to
          ``run_calibration_cli`` with the given TOML path. Extra keyword
          arguments are forwarded.
        * Python mode (``parameters`` supplied): build a
          :class:`CalibrationConfig` in memory from the declarations and
          run the same loop.
        * Embedded mode (neither supplied): use the ``[calibration]`` section
          carried by this project's config, so a fully in-memory
          ``HydroModPyConfig`` calibrates without re-declaring parameters.

        A configuration declaring ``[[calibration.phases]]`` **routes** to
        :func:`~hydromodpy.calibration.runners.staged_runner.run_staged_calibration`
        in TOML mode, and in embedded mode when this project was built from a
        file. Python mode routes there too when ``phases`` is given, and so
        does an embedded declaration on a project built in memory: both write
        the calibration document the staged runner needs (next to this
        project's ``sessions/``) and run it from there, since there is no
        source file to fork each phase from otherwise. Python mode without
        ``phases`` declares its own single-stage parameter space, so the
        phases of the project config do not apply to it.

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
        phases
            Python-mode phase declarations, one dict per phase, same keys as
            ``[[calibration.phases]]``. Runs staged, through the same document
            and runner as a TOML calibration that declares phases.
        method
            Optimizer method name. Unset, the one the criteria call for: a root
            search for one log parameter scored on signed criteria only, a
            minimiser otherwise.
        max_iter
            Maximum number of optimizer iterations.
        save_runs
            Policy controlling which trial runs remain persisted.
        seed
            Optional optimizer seed.
        phase
            Run only the named phase of a staged calibration.
        kwargs
            Extra options forwarded to the calibration runner.

        Returns
        -------
        CalibrationReport or StagedCalibrationReport or dict
            A :class:`CalibrationReport` for a calibration without phases, a
            :class:`StagedCalibrationReport` for one that declares phases, in
            every mode. ``return_report=False`` returns the ``to_dict()``
            payload of that report instead.

        Raises
        ------
        ConfigMissingError
            Raised when neither ``config_path`` nor ``parameters`` is supplied.
        ConfigError
            Raised when ``phase`` is given and ``config_path`` cannot be read,
            because the answer is what the file says.
        CalibrationError
            Raised when ``[[calibration.phases]]`` cannot be run as declared,
            and when ``phase`` names a phase no configuration declares.
        """
        from hydromodpy.core.exceptions import CalibrationError, ConfigMissingError
        from hydromodpy.project.dispatch.workflow import (
            calibration_phases_or_raise,
            declared_calibration_phases,
            no_such_phase,
        )

        if config_path is not None:
            from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

            target = Path(config_path).expanduser().resolve()
            # Routing alone tolerates an unreadable file: the runner that reads
            # it next reports the failure with its own context. Selecting a
            # phase by name reaches no runner, so the failure has to surface
            # here, or the user is sent looking at a phases block that is
            # present and correct.
            if phase is not None:
                declared_phases = calibration_phases_or_raise(target)
            else:
                declared_phases = declared_calibration_phases(target)
            if declared_phases:
                from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

                return run_staged_calibration(target, phase=phase, **kwargs)
            if phase is not None:
                raise CalibrationError(no_such_phase(target.name, phase))
            # The plain runner returns its dict unless asked; every other
            # branch returns the report object by default.
            kwargs.setdefault("return_report", True)
            return run_calibration_cli(target, **kwargs)

        from hydromodpy.calibration.config import CalibrationConfig
        from hydromodpy.calibration.runners.programmatic_runner import run_calibration_programmatic

        if not parameters:
            # Fall back to the [calibration] section carried by this project's
            # config, so a fully in-memory HydroModPyConfig calibrates without
            # re-declaring parameters= (matches the TOML path).
            embedded = getattr(getattr(self, "config", None), "calibration", None)
            if embedded is not None:
                declared = [decl.name for decl in (getattr(embedded, "phases", None) or [])]
                source = self._config_path
                if declared and source is not None:
                    from hydromodpy.calibration.runners.staged_runner import (
                        run_staged_calibration,
                    )

                    return run_staged_calibration(Path(source).resolve(), phase=phase, **kwargs)
                if not declared and phase is not None:
                    raise CalibrationError(no_such_phase("this configuration", phase))
                # A declaration on a project built in memory has no file to fork
                # each phase from: run_calibration_programmatic writes one next
                # to this project's sessions/ and runs the staged runner on it.
                return run_calibration_programmatic(
                    embedded,
                    project=self,
                    workspace=kwargs.get("workspace"),
                    project_label=kwargs.get("project_label", kwargs.get("project")),
                    metric_fn=kwargs.get("metric_fn"),
                    objective=kwargs.get("objective"),
                    return_report=kwargs.get("return_report", True),
                    phase=phase,
                )
            raise ConfigMissingError(
                "Project.calibrate() requires either config_path=, parameters= "
                "(Python-mode declaration), or a [calibration] section in the "
                "project config."
            )

        if phase is not None and not phases:
            raise CalibrationError(no_such_phase("this parameters= declaration", phase))

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
        if phases is not None:
            payload["phases"] = list(phases)
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
        # Completed from the target each parameter names, as the TOML route does,
        # so a bare K searches the log space its field declares and gets the
        # same method as the same file would.
        project_config = getattr(self, "config", None)
        if project_config is not None:
            from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets

            resolve_parameter_targets(cfg, project_config)
        return run_calibration_programmatic(
            cfg,
            project=self,
            workspace=kwargs.get("workspace"),
            project_label=kwargs.get("project_label", kwargs.get("project")),
            metric_fn=kwargs.get("metric_fn"),
            objective=kwargs.get("objective"),
            return_report=kwargs.get("return_report", True),
            phase=phase,
        )

    def spinup(
        self,
        *,
        spinup: SpinupConfig | None = None,
        name_prefix: str = "spinup",
    ) -> SpinupResult:
        """Run the cyclic spin-up loop on this project.

        Restarts the representative window each cycle from the previous cycle's
        state until the aquifer heads and the lake stage converge. Defaults to
        the ``[spinup]`` section of this project's config; pass ``spinup`` to
        override it in memory. Feed ``result.restart_from`` to a production
        run's ``[flow] restart_from``.

        Parameters
        ----------
        spinup
            Spin-up settings override. ``None`` uses ``config.spinup``.
        name_prefix
            Prefix for the per-cycle run names recorded in the catalog.

        Returns
        -------
        hydromodpy.project.spinup.SpinupResult
            The loop outcome (converged state, ``restart_from`` handle).
        """
        from hydromodpy.project.spinup import run_spinup

        return run_spinup(self, spinup=spinup, name_prefix=name_prefix)

    # -- Lifecycle --------------------------------------------------------

    def close(self) -> None:
        """Close the Catalog and clean up preprocessing files."""
        self._catalog.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self) -> str:
        if self._state.root is not None:
            return f"Project({str(self._state.root)!r})"
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
            ("solver", str(self._state.solver or "&mdash;")),
            ("headless", "yes" if self._state.headless else "no"),
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


def open_project(path: str | Path) -> Project:
    """Open the project a directory, or a file inside it, belongs to, read only.

    The project root is the folder of ``project.toml`` at or above *path*.
    Nothing is validated or built: the project reads its plan, its runs and
    its sessions from the disk, and reads ``project.toml`` only when a model
    verb (``simulate``, ``prepare``, ``config`` ...) needs a configuration.
    """
    start = Path(path).expanduser().resolve()
    root = resolve_project_root(start.parent if start.is_file() else start).resolve()
    project = object.__new__(Project)
    object.__setattr__(project, "_state", ProjectState(root=root))
    object.__setattr__(project, "_runner", ProjectRunner(project))
    object.__setattr__(project, "_catalog", ProjectCatalog(project))
    return project
