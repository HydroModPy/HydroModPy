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

The facade holds the public verbs; they delegate to:

- :class:`hydromodpy.project.runner.ProjectRunner` (``project._runner``):
  internal runner backing ``simulate`` / ``calibrate``.
- :class:`hydromodpy.project.catalog.ProjectCatalog` (``project._catalog``):
  catalog access (``store``, ``runs``, ``data``) and lifecycle (``close``).
- :mod:`hydromodpy.project.phases`: model-phase verbs that mutate the
  project directly (``configure``, ``setup_workspace``, ``build_geographic``,
  ``load_data``, ``build_mesh``).
- :mod:`hydromodpy.project.accessors`: the reads of a project directory
  (``cases``, ``sites``, ``best``, ``runs``, ``sessions``).
- :mod:`hydromodpy.project.calibrate`: the runner a calibration goes to.

A project is also opened on its directory, read only, by ``hmp.open``
(:func:`~hydromodpy.project.opening.open_project`). It then reads its plan,
its runs and its sessions from the disk, and launches its cases with the words
of ``hmp project``: ``plan``, ``launch``, ``status``, ``collect``, ``publish``.
Its configuration is read from ``project.toml`` only when a model verb needs it.

Example
-------
::

    import hydromodpy as hmp

    project = hmp.Project("project.toml")  # cheap: validates config
    run = project.simulate(
        set={"Sy": 0.05, "K": 5e-5}, name="baseline"
    )  # builds, then runs
    wt = run.field("watertable_depth", time=12)

    # Parameter sweep: one simulate() per value
    for sy in (0.01, 0.05, 0.1):
        project.simulate(name=f"sy_{sy}", set={"Sy": sy})

    project.close()

    proj = hmp.open("projects/bretagne_k")  # a [sites] project, read only
    proj.cases  # the plan joined to the outcomes
    proj.best_runs("nse", by="site")  # the best calibrated run of each site
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hydromodpy.core.config_kit.base import frozen_copy
from hydromodpy.core.exceptions import ConfigMissingError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.old_members import refuse_old_member
from hydromodpy.core.state.paths import run_scratch, summary_dir_for
from hydromodpy.core.toml_io.paths import assign, parse
from hydromodpy.project import opening
from hydromodpy.project import phases as project_phases
from hydromodpy.project.accessors import (
    ProjectDataAccessor,
    ProjectRunsAccessor,
    ProjectSessions,
    best_frame,
    cases_frame,
    sites_frame,
)
from hydromodpy.project.catalog import ProjectCatalog
from hydromodpy.project.runner import ProjectRunner
from hydromodpy.project.state import (
    CONFIGURED_STATE_FIELDS,
    PROJECT_ATTR_TO_STATE_FIELD,
    ProjectState,
)
from hydromodpy.results.validity_rules import CALIBRATED_LABELS
from hydromodpy.workflow.record.resume import scratch_of_resumed_run

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd

    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.config.sites.expansion import PlanDraft
    from hydromodpy.core.state.data import LoadedDataContext
    from hydromodpy.core.time.window import (
        ResolvedSimulationTimeGrid,
        ResolvedSteadySimulationTimeGrid,
    )
    from hydromodpy.project.launch import LaunchReport, StatusReport
    from hydromodpy.project.launch.summary import SummaryPaths
    from hydromodpy.project.spinup import SpinupResult
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.checks import CalibratedBy
    from hydromodpy.results.lineage import Lineage
    from hydromodpy.results.publication import PublicationExtra, PublicationFormat
    from hydromodpy.results.run import Run
    from hydromodpy.simulation.spinup_config import SpinupConfig
    from hydromodpy.spatial.domain.domain import Domain
    from hydromodpy.spatial.geographic.catchment_delineation import (
        CatchmentDelineation,
    )
    from hydromodpy.workflow.record.attempt import SealedRun

logger = get_logger(__name__)


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
        Flow solver of a configuration that declares no process. One that declares
        another solver is refused: the plan and the replay read the configuration.
    headless : bool, optional
        Draw no figure (useful for calibration loops where generating figures
        per iteration is wasteful). A choice of this launch: it changes neither
        the identity of a run, nor its sealed configuration, nor what it keeps.
    no_display : bool, optional
        The same, said by the option of ``hmp run``.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> project = hmp.Project("project.toml")  # doctest: +SKIP
    >>> run = project.simulate(set={"Sy": 0.05})  # doctest: +SKIP
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
        object.__setattr__(self, "_state", ProjectState())
        project_phases.configure(
            self,
            opening.resolve_config(config),
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
                    opening.configure_opened(self)
                return getattr(state, target)
        refuse_old_member("Project", name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    @classmethod
    def rerun(
        cls,
        run: Run,
        *,
        name: str | None = None,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        solver: str | None = None,
        headless: bool = False,
        no_display: bool = False,
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
        set
            Values to set on the stored configuration, as in :meth:`simulate`: a dotted
            path, the grammar of ``--set``, or a name of ``hmp config targets``. The result
            is validated, so an unknown key raises.
        solver, headless, no_display
            Options forwarded to the derived :class:`Project`.

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

        from hydromodpy.project.dispatch.rerun import rerun_config

        new_run = rerun_config(
            snapshot,
            changes=set or {},
            name=name,
            source_sim_id=run.sim_id,
            source_dir=run.dir,
            project_options={"solver": solver, "headless": headless, "no_display": no_display},
        )
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
        project_phases.setup_workspace(self)

    def build_geographic(self, *, reuse_dem: bool = False) -> None:
        """Mark geographic/domain runtime ready and invalidate downstream state."""
        project_phases.build_geographic(self, reuse_dem=reuse_dem)

    def load_data(self, *, types: list[str] | None = None) -> None:
        """Load the external forcings declared in [data]."""
        project_phases.load_data(self, types=types)

    def reload_data(self, *, types: list[str]) -> None:
        """Reload a subset of data variables without touching the others."""
        project_phases.reload_data(self, types=types)

    def rebuild_geographic(self, *, reuse_dem: bool = False) -> None:
        """Rerun the geographic pipeline and invalidate the mesh."""
        project_phases.rebuild_geographic(self, reuse_dem=reuse_dem)

    def build_mesh(self, **overrides) -> None:
        """Build the catchment mesh from the current geographic context."""
        project_phases.build_mesh(self, **overrides)

    @property
    def config(self) -> HydroModPyConfig:
        """A frozen copy of the configuration of this project, taken at each read.

        Assigning to it raises :class:`~hydromodpy.core.exceptions.FrozenConfigError`. A
        run takes its changes by ``simulate(set=...)``. A configuration takes them by
        ``HydroModPyConfig.with_changes``, and the result opens a new :class:`Project`.
        """
        return frozen_copy(self._cfg)

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
        return opening.refreshed_index(self)

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

    def best_runs(
        self,
        metric: str = "nse",
        *,
        by: Literal["site", "recipe"] | None = "site",
        label: str | Sequence[str] | None = CALIBRATED_LABELS,
        mixed_windows: bool = False,
    ) -> pd.DataFrame:
        """Return the best completed run of each site, one row each, as a table.

        ``best`` names one :class:`~hydromodpy.results.run.Run` everywhere else:
        ``proj.runs().best(metric)`` is the run itself.

        The metric is read at the gauge of each run, in the window of its
        rule; best follows its direction. The calibrated runs are ranked by
        default, the ``evaluated`` ones included (scored out of their
        calibration window); ``label="calibrated"`` keeps the runs scored in
        it, ``label=None`` ranks every completed run. ``by=None`` gives
        the single best run of the project. A site of completed runs left
        out is named once in a warning, with why: no run scored (declare
        ``[metrics] window``), or none of ``label``.

        Returns
        -------
        pandas.DataFrame
            ``site`` (or ``recipe``), ``case_id``, ``rel_dir``, ``sim_id``,
            ``label``, the global parameters (``K`` ...), the metric under
            its own name, ``station``, ``window_start``, ``window_end``.

        Examples
        --------
        >>> proj = hmp.open("projects/bretagne_k")  # doctest: +SKIP
        >>> proj.best_runs("nse", by="site")  # doctest: +SKIP
        """
        return best_frame(self._index(), metric, by=by, label=label, mixed_windows=mixed_windows)

    def plan(
        self,
        *,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        force: bool = False,
    ) -> PlanDraft:
        """Resolve the cases of a ``[sites]`` project and write ``plan/<hash>/``.

        The words of ``hmp project plan``, with the changes of ``--set`` by dotted path. A
        plan is not rewritten while one of its cases runs, unless ``force``.
        """
        from hydromodpy.project.launch import plan_project

        payload: dict[str, Any] = {}
        for dotted, value in (set or {}).items():
            assign(payload, parse(dotted), value)
        return plan_project(self.root, set_overrides=payload, force=force)

    def launch(
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
        counts its own ``[calibration] parallel``. :meth:`simulate` runs one simulation.
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

        The words of ``hmp campaign collect``.
        """
        from hydromodpy.project.launch.summary import collect_project

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

    def _run_scratch(self, name: str | None, resume: str | None):
        """Enter the scratch folder of the run ``name`` (or the case ``resume``) names."""
        label = name or resume or self._cfg.simulation.name or "run"
        project_root = Path(self._cfg.workspace.project_root)
        resumes = scratch_of_resumed_run(project_root, resume) if resume is not None else None
        return run_scratch(project_root, label, resumes=resumes)

    def _execute(
        self,
        *,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        name: str | None = None,
        resume: str | None = None,
        from_step: str | None = None,
        until_step: str | None = None,
        frozen: bool = False,
        no_display: bool = False,
        fresh: bool = False,
        force: bool = False,
        lineage: Lineage | None = None,
        calibrated_by: CalibratedBy | None = None,
    ) -> SealedRun | None:
        """Run one attempt of the case and return what its directory says.

        The worker verb: it claims ``runs/<case>/``, runs the Pipeline, seals
        the run and closes its outcome, and never opens the index of the
        project. ``hmp run`` stops here and indexes afterwards. The keywords
        are those of :meth:`simulate`, without ``dry_run``.
        """
        with self._run_scratch(name, resume):
            return self._runner.execute(
                set=set,
                name=name,
                resume=resume,
                from_step=from_step,
                until_step=until_step,
                frozen=frozen,
                no_display=no_display,
                fresh=fresh,
                force=force,
                lineage=lineage,
                calibrated_by=calibrated_by,
            )

    def simulate(
        self,
        *,
        set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
        name: str | None = None,
        resume: str | None = None,
        from_step: str | None = None,
        until_step: str | None = None,
        dry_run: bool = False,
        frozen: bool = False,
        no_display: bool = False,
        fresh: bool = False,
        force: bool = False,
        lineage: Lineage | None = None,
        calibrated_by: CalibratedBy | None = None,
    ) -> Run | PlanDraft | None:
        """Run one simulation through the configured workflow and return its result.

        Builds the model phase on first call (lazy), then runs the Pipeline.
        A run bounded by ``until_step`` before ``setup_process`` needs no shared
        model phase: it executes its own steps and builds nothing else, which is
        how a catchment is delineated without loading data or meshing.
        Call once per point to sweep a parameter.
        Once the attempt is closed, the index of the project is refreshed from
        the run directory and the :class:`Run` view is returned.

        Parameters
        ----------
        set
            Changes of the configuration of this run. A key is a dotted path, the grammar
            of ``--set``, or a name of ``hmp config targets`` such as ``K``, ``Sy`` or
            ``thickness``, or ``first_clim``, in the unit the configuration declares for
            it. They are applied before its plan is built, written in its sealed
            ``config.toml``, recorded by dotted path in ``lineage.overrides``, and a rerun
            repeats them.
        name
            Run name, the case the directory is named after. Defaults to
            ``[simulation] name`` of the configuration, and to ``run_0001``,
            ``run_0002``... only when the configuration names no run.
        resume
            Name of an interrupted case to continue in place from its journal.
        from_step, until_step
            Bounds of a partial run: names of pipeline steps, listed in
            :data:`~hydromodpy.core.pipeline_steps.STEP_NAMES`.
        dry_run
            Say what this run would do, and run nothing.
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

        Returns
        -------
        Run or PlanDraft or None
            The persisted run view, or its ``PlanDraft`` for a dry run. ``None`` when the
            run keeps nothing to read: a window that stops before ``setup_process``.

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
        >>> run = project.simulate(set={"Sy": 0.05}, name="probe")  # doctest: +SKIP
        >>> run.label()  # doctest: +SKIP

        See Also
        --------
        hydromodpy.run
            Functional facade for one-off TOML execution.
        hydromodpy.results.run.Run
            Per-simulation result view returned by successful runs.
        """
        if dry_run:
            return self._runner.draft(
                set=set, name=name, resume=resume, from_step=from_step, until_step=until_step
            )
        with self._run_scratch(name, resume):
            return self._runner.run(
                set=set,
                name=name,
                resume=resume,
                from_step=from_step,
                until_step=until_step,
                frozen=frozen,
                no_display=no_display,
                fresh=fresh,
                force=force,
                lineage=lineage,
                calibrated_by=calibrated_by,
            )

    def calibrate(
        self,
        *,
        config_path: str | Path | None = None,
        parameters: dict[str, dict] | None = None,
        outputs: dict[str, dict] | None = None,
        objective_blocks: list[dict] | None = None,
        phases: list[dict] | None = None,
        protocol: str | dict | None = None,
        method: str | None = None,
        max_trials: int | None = None,
        save_runs: str | None = None,
        seed: int | None = None,
        phase: str | None = None,
        case: str | None = None,
        resume: bool = False,
        dry_run: bool = False,
        workspace: str | Path | None = None,
        project: str | None = None,
        project_label: str | None = None,
        metric_fn: Any = None,
        objective: str | None = None,
    ):
        """Run a calibration campaign on this project.

        Three modes are supported:

        * TOML mode (``config_path`` supplied): delegate to
          ``run_calibration_cli`` with the given TOML path.
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
        max_trials
            Maximum number of optimizer iterations.
        save_runs
            Policy controlling which trial runs remain persisted.
        seed
            Optional optimizer seed.
        phase
            Run only the named phase of a staged calibration.
        protocol
            Name of a calibration protocol, or a table naming one. It is laid over
            this project's own ``[calibration]`` section, which keeps the parameters
            and outputs the protocol reads, so it excludes ``config_path`` and
            ``parameters``.
        case
            Name of the case, so of the session, of an in-memory calibration. A file
            names its case with ``[simulation] name``.
        resume
            Reopen the latest session of the case; the trials already journaled
            preload the cache.
        dry_run
            Return the plan a launch would follow, a ``dict``, after the checks of
            ``hmp config check``, and run nothing. A calibration held in memory needs
            a project built from a file to name its case.
        workspace, project, project_label, metric_fn, objective
            Runner options: the project root, the project name written in the session
            (``project_label`` wins), a metric extractor, and ``"module:callable"``
            naming one.

        Returns
        -------
        CalibrationReport
            What the calibration found, with or without phases, in every mode.
            With ``dry_run``, the plan.

        Raises
        ------
        ConfigMissingError
            Raised when neither ``config_path`` nor ``parameters`` is supplied.
        ConfigError
            Raised when ``phase`` is given and ``config_path`` cannot be read,
            because the answer is what the file says, and when the preflight,
            the checks of ``hmp config check``, refuses the calibration, before
            anything is prepared.
        CalibrationError
            Raised when ``[[calibration.phases]]`` cannot be run as declared,
            and when ``phase`` names a phase no configuration declares.
        """
        from hydromodpy.project.calibrate import calibrate_project

        return calibrate_project(
            self,
            config_path=config_path,
            parameters=parameters,
            outputs=outputs,
            objective_blocks=objective_blocks,
            phases=phases,
            protocol=protocol,
            method=method,
            max_trials=max_trials,
            save_runs=save_runs,
            seed=seed,
            phase=phase,
            case=case,
            resume=resume,
            dry_run=dry_run,
            workspace=workspace,
            project=project,
            project_label=project_label,
            metric_fn=metric_fn,
            objective=objective,
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
        return opening.project_repr(self)

    def _repr_html_(self) -> str:
        return opening.project_html(self)
