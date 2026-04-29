"""High-level Project API for interactive Python usage.

Setup-once, run-many interface that wraps the launcher's internal phases
behind a clean API.  The TOML-driven workflow (``hmp run``) is unchanged;
this module provides the **programmatic** equivalent.

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

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = logging.getLogger(__name__)


DEFAULT_RUN_NAME_TEMPLATE = "run_{counter:04d}"


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
    raise ValueError(f"Unknown pipeline step: {step!r}. Known steps: {known}")


def _resolve_resume_step_index(workspace: Path, run_id: str) -> int:
    """Locate the next step index to execute for a previously interrupted run."""
    from hydromodpy.workflow.internals.checkpoint import CheckpointStore
    from hydromodpy.workflow.internals.ledger import StepsLedger

    cp = CheckpointStore(workspace, run_id)
    last = cp.latest()
    if last is None:
        raise RuntimeError(
            f"No checkpoints found for run_id '{run_id}' in {cp.dir}. "
            "Start a fresh run instead of using resume."
        )
    resume_from = last + 1

    ledger = StepsLedger(workspace)
    last_completed = ledger.last_completed(run_id)
    ledger.close()
    if last_completed is not None:
        resume_from = max(resume_from, last_completed + 1)
    return resume_from


def _print_dry_run_plan(
    *,
    run_id: str,
    steps: tuple,
    resume_from: int | None,
    checkpoint: bool,
) -> None:
    """Emit the resolved Pipeline plan without executing any step."""
    print(f"[dry-run] run_id    : {run_id}")
    print(f"[dry-run] checkpoint: {'enabled' if checkpoint else 'disabled'}")
    if resume_from is not None:
        print(f"[dry-run] resume_from: {resume_from}")
    print("[dry-run] steps     :")
    for idx, step in enumerate(steps):
        print(f"  {idx:02d}  {type(step).__name__}")


# =====================================================================
# Project
# =====================================================================


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

    Full Python, no TOML — build the config with Pydantic directly::

        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

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
        self._configure(
            config,
            solver=solver,
            headless=headless,
            no_display=no_display,
        )
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
    def from_json(cls, payload: dict, **kwargs) -> Project:
        """Build a Project from a JSON payload validated against HydroModPyConfig."""
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        cfg = HydroModPyConfig.model_validate(payload)
        return cls(cfg, **kwargs)

    def _configure(
        self,
        config: str | Path | object,
        *,
        solver: str | None,
        headless: bool,
        no_display: bool,
    ) -> None:
        """Resolve the config, time grid and data plan, then build an empty ctx."""
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.core.config.toml_loader import load_toml_with_base_config
        from hydromodpy.core.time import (
            apply_explicit_time_window_to_tgrids,
            require_flow_simulation_time_grid,
        )
        from hydromodpy.data import DataPlanner
        from hydromodpy.spatial.domain.spatial_support import (
            build_default_spatial_support_provider_registry,
        )
        from hydromodpy.workflow.context import WorkflowContext
        from hydromodpy.workflow.steps.data_loading import log_data_plan
        from hydromodpy.workflow.steps.mesh import (
            resolve_optional_mesh_input,
            resolve_optional_mesh_section,
        )
        from hydromodpy.workflow.steps.setup import (
            collect_requested_support_ids,
            resolve_support_configs,
            support_provider_names,
        )

        if isinstance(config, HydroModPyConfig):
            self._config_path = None
            self.cfg = config
            raw_toml: dict = {}
        else:
            self._config_path = Path(config).resolve()
            self.cfg = HydroModPyConfig.from_toml(self._config_path)
            raw_toml = load_toml_with_base_config(self._config_path)

        self._solver = solver or self._detect_solver()
        self._ensure_simulation_block()

        apply_explicit_time_window_to_tgrids(self.cfg)
        self._time_grid = require_flow_simulation_time_grid(self.cfg)

        if self._config_path is not None:
            self._mesh_section_data = resolve_optional_mesh_section(raw_toml)
            self._external_mesh_input = resolve_optional_mesh_input(
                raw_toml,
                self._config_path,
            )
        else:
            self._mesh_section_data = None
            self._external_mesh_input = None
        self._mesh_constraints_mode = None
        if self._mesh_section_data is not None and self._external_mesh_input is not None:
            raise ValueError(
                "Embedded [mesh_catchment] and external [mesh_input] are mutually "
                "exclusive. Use only one mesh source."
            )
        if self._mesh_section_data is not None:
            from hydromodpy.spatial.mesh.runtime import (
                prepare_geographic_config_for_meshing,
            )

            self._mesh_constraints_mode = self._mesh_section_data.constraints_mode
            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode=self._mesh_constraints_mode,
            )
        elif self._external_mesh_input is not None and "stream" in {
            str(bc_id).strip().lower() for bc_id in getattr(self.cfg.flow, "active_bc", ())
        }:
            from hydromodpy.spatial.mesh.runtime import (
                prepare_geographic_config_for_meshing,
            )

            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode="rivers_only",
                section_name="mesh_input",
            )

        self._spatial_support_registry = build_default_spatial_support_provider_registry()
        self._requested_support_ids = collect_requested_support_ids(self.cfg.flow)
        self._requested_domain_supports = resolve_support_configs(
            self.cfg.domain,
            self._requested_support_ids,
        )

        data_plan = DataPlanner().build(
            self.cfg.data,
            domain_zone_ids=self.cfg.domain.zone_ids,
            domain_support_provider_names=support_provider_names(
                self._requested_domain_supports,
            ),
            requested_spatial_support_ids=self._requested_support_ids,
            raw_toml=raw_toml,
            flow_active_bc=self.cfg.flow.active_bc,
        )
        log_data_plan(data_plan)
        self.cfg.data = self.cfg.data.with_resolved_types(data_plan.types)

        self._ctx = WorkflowContext(
            cfg=self.cfg,
            config_path=self._config_path or Path.cwd(),
            raw_toml=raw_toml,
        )
        self._ctx.data_plan = data_plan
        self._ctx.setup.time_grid = self._time_grid

        self._headless = headless
        self._no_display = no_display
        if headless:
            self.cfg.display.save = False
            self.cfg.display.show = False

        self._store = None
        self._project_name: str | None = None
        self._run_counter = 0
        self._active_runs: dict[str, str] = {}
        self._last_wall_seconds: dict[str, float] = {}
        self._phase: str = "uninitialized"
        self._data_loaded: set[str] = set()
        source = self._config_path.name if self._config_path else "<in-memory config>"
        logger.info("Project configured: %s", source)

    # -- Model-phase verbs -------------------------------------------------

    def setup_workspace(self) -> None:
        """Materialize the workspace and structural objects (Domain, Flow, Transport).

        Idempotent: calling twice resets the structural objects. Opens the catalog
        as a side effect so later run-phase methods can register simulations.
        """
        from hydromodpy.workflow.steps.setup import step_setup
        from hydromodpy.workflow.steps.spatial_supports import step_spatial_supports

        step_setup(
            self._ctx,
            requested_spatial_support_ids=self._requested_support_ids,
            requested_domain_supports=self._requested_domain_supports,
        )
        step_spatial_supports(
            self._ctx,
            phase="setup",
            requested_domain_supports=self._requested_domain_supports,
            registry=self._spatial_support_registry,
        )
        self._phase = "workspace"
        self._open_catalog()

    def build_geographic(self, *, reuse_dem: bool = False) -> None:
        """Build the geographic runtime (DEM, watershed, topography).

        Runs setup_workspace first when it has not happened yet so the
        geographic runtime has a workspace to live in. Invalidates mesh.
        """
        if self._phase == "uninitialized":
            self.setup_workspace()
        self._phase = "geographic"
        self._data_loaded.clear()
        self._ctx.setup.mesh_planar = None
        self._ctx.setup.mesh_bundle = None

    def load_data(self, *, types: list[str] | None = None) -> None:
        """Load the external forcings declared in [data].

        ``types=None`` loads every declared variable. Any subset filters the
        loaded types and is tracked in :attr:`data_loaded`.
        """
        from hydromodpy.workflow.steps.data_loading import step_data_loading
        from hydromodpy.workflow.steps.spatial_supports import step_spatial_supports

        if self._phase == "uninitialized":
            self.build_geographic()
        step_data_loading(self._ctx)
        step_spatial_supports(
            self._ctx,
            phase="data",
            requested_domain_supports=self._requested_domain_supports,
            registry=self._spatial_support_registry,
        )
        if types is None:
            self._data_loaded = set(getattr(self._ctx.data_plan, "types", ()))
        else:
            self._data_loaded.update(types)
        self._phase = "data"

    def reload_data(self, *, types: list[str]) -> None:
        """Reload a subset of data variables without touching the others.

        Thin wrapper around :meth:`load_data` that makes intent explicit in
        calibration or notebook loops.
        """
        self.load_data(types=list(types))

    def rebuild_geographic(self, *, reuse_dem: bool = False) -> None:
        """Rerun the geographic pipeline and invalidate the mesh."""
        self.build_geographic(reuse_dem=reuse_dem)

    def build_mesh(self, **overrides) -> None:
        """Build the catchment mesh from the current geographic context.

        ``overrides`` is accepted for future per-call mesh config patches but is
        currently ignored: apply changes to ``project.cfg.mesh_catchment``
        before calling this verb.
        """
        from hydromodpy.workflow.steps.mesh import step_mesh, step_mesh_input

        if self._phase == "uninitialized":
            self.load_data()
        step_mesh(
            self._ctx,
            mesh_section_data=self._mesh_section_data,
            constraints_mode=self._mesh_constraints_mode,
        )
        step_mesh_input(self._ctx, external_mesh_input=self._external_mesh_input)
        self._phase = "ready"

    def _open_catalog(self) -> None:
        """Open the SimulationCatalog for this workspace (idempotent)."""
        from hydromodpy.results.catalog import SimulationCatalog

        if self._store is not None:
            return
        ws = self._ctx.setup.workspace
        if ws is None:
            return
        self._store = SimulationCatalog(ws.root)
        self._project_name = ws.project_root.name

    # -- Inspection properties --------------------------------------------

    @property
    def phase(self) -> str:
        """Current model-phase: uninitialized, workspace, geographic, data, mesh, ready."""
        if self._phase == "data" and self._ctx.setup.mesh_planar is not None:
            return "mesh"
        return self._phase

    @property
    def has_workspace(self) -> bool:
        return self._ctx.setup.workspace is not None

    @property
    def has_geographic(self) -> bool:
        return self._ctx.setup.geographic is not None

    @property
    def has_data(self) -> bool:
        return bool(self._data_loaded)

    @property
    def has_mesh(self) -> bool:
        return self._ctx.setup.mesh_planar is not None

    @property
    def is_ready_for_run(self) -> bool:
        return self.has_workspace and self.has_mesh and self._store is not None

    @property
    def data_loaded(self) -> set[str]:
        """Set of data types already loaded for this project."""
        return set(self._data_loaded)

    @property
    def data(self) -> _ProjectDataAccessor:
        """Accessor for the input-data cache scoped to this project."""
        return _ProjectDataAccessor(self)

    @property
    def runs(self) -> _ProjectRunsAccessor:
        """Accessor for the simulation catalog scoped to this project."""
        return _ProjectRunsAccessor(self)

    def __getitem__(self, sim_id: str):
        """Return the Run view associated with ``sim_id``."""
        return self._store[sim_id]

    # -- Public properties -------------------------------------------------

    @property
    def geographic(self):
        """Geographic runtime object (DEM, watershed, CRS)."""
        return self._ctx.setup.geographic

    @property
    def domain(self):
        """Spatial domain (mesh, layers, zones)."""
        return self._ctx.setup.domain

    @property
    def store(self):
        """Open SimulationCatalog for direct queries across all runs."""
        return self._store

    @property
    def time_grid(self):
        """Resolved simulation time grid."""
        return self._time_grid

    @property
    def loaded_data(self):
        """Loaded data context (recharge, geology, hydrometry, etc.)."""
        return self._ctx.loaded_data

    # -- Run ---------------------------------------------------------------

    def prepare(self, *, name: str | None = None, **overrides) -> str:
        """Reserve a sim_id, register the simulation and persist all inputs.

        Returns the sim_id. The caller can then execute, ingest, render and
        cleanup explicitly, or let :meth:`run` chain them. ``overrides`` match
        :meth:`run`: K/Sy/Ss (homogeneous flow params), ``thickness``,
        ``first_clim``, ``properties``.
        """
        from hydromodpy.workflow.orchestrator import prepare_run

        self._run_counter += 1
        sim_id = str(uuid4())
        if name is None:
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=self._run_counter)

        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

        self._ctx.store = self._store
        final_name = prepare_run(
            self._ctx,
            sim_id=sim_id,
            name=name,
            project_name=self._project_name,
            overrides=overrides,
            thickness=thickness,
            first_clim=first_clim,
            solver=self._solver,
            properties=properties,
        )
        self._active_runs[sim_id] = final_name
        return sim_id

    def execute(self, sim_id: str) -> float:
        """Run the solver for a previously prepared simulation.

        Returns wall-clock seconds for the run.
        """
        from hydromodpy.workflow.orchestrator import execute_run

        final_name = self._active_runs.get(sim_id, self._ctx.setup.run_id)
        wall = execute_run(self._ctx, sim_id, final_name=final_name)
        self._last_wall_seconds[sim_id] = wall
        return wall

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations for a completed simulation."""
        from hydromodpy.workflow.orchestrator import ingest_run

        ingest_run(self._ctx, sim_id, extractors=extractors)

    def render(
        self,
        sim_id: str,
        *,
        figures: list[str] | None = None,
    ) -> list[Path]:
        """Render the display figures attached to this simulation."""
        from hydromodpy.workflow.orchestrator import render_run

        run = self._store[sim_id]
        final_name = self._active_runs.get(sim_id, self._ctx.setup.run_id)
        return render_run(
            self._ctx,
            sim_id,
            run=run,
            figures=figures,
            headless=self._headless,
            no_display=self._no_display,
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

        wall = self._last_wall_seconds.pop(sim_id, 0.0)
        cleanup_run(
            self._ctx,
            sim_id,
            keep_solver_files=keep_solver_files,
            wall_seconds=wall,
            save_artifacts=False,
            close_store=False,
            status=status,
        )
        self._active_runs.pop(sim_id, None)

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

        Parameters
        ----------
        name
            Run label. Auto-generated when omitted.
        checkpoint
            Persist a checkpoint after each step.
        resume
            Resume the run with this id from its last successful checkpoint.
        from_step
            Start from a specific step (name or index). Mutually exclusive
            with ``resume``: ``resume`` infers the index from the checkpoint
            store, ``from_step`` sets it explicitly.
        until_step
            Stop after the specified step (name or index).
        dry_run
            Print the resolved step plan and return ``None`` without
            executing.
        frozen
            Toggle process-wide frozen mode (no fresh data downloads).
        no_display
            Skip the auto-rendering DisplayStep at pipeline end.
        **overrides
            Flow parameter overrides forwarded to ``step_build_plan``.

        Returns
        -------
        Run or None
            The persisted Run view, or ``None`` for ``dry_run=True``.
        """
        from hydromodpy.workflow.internals.state import PipelineState
        from hydromodpy.workflow.orchestrator import standard_steps
        from hydromodpy.workflow.runner import Pipeline
        from hydromodpy.workflow.steps.plan_building import step_build_plan

        if frozen:
            from hydromodpy.data.lockfile import set_frozen_mode

            set_frozen_mode(True)

        skip_display = bool(self._no_display) or bool(no_display)

        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

        if name is None:
            self._run_counter += 1
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=self._run_counter)

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
            resume_from = _resolve_resume_step_index(workspace_path, resume)
            run_id = resume
        elif self._is_model_phase_ready():
            # Project's eager init already produced the workspace, geographic
            # runtime, domain and mesh. Skip those steps to keep behaviour
            # identical to the legacy verb-by-verb path.
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
                checkpoint=checkpoint,
            )
            return None

        # Always rebuild the plan so each call picks up cfg edits and gets a
        # fresh ``execution.process_runs_by_id`` mapping.
        step_build_plan(
            self._ctx,
            name=name,
            overrides=overrides or {},
            thickness=thickness,
            first_clim=first_clim,
            solver=self._solver,
        )

        if properties is not None:
            self._ctx.setup.flow_runtime_overrides = {
                "source": "project_run",
                "properties": dict(properties),
            }
        else:
            self._ctx.setup.flow_runtime_overrides = None

        self._ctx.setup.run_id = name

        # Release Project's catalog handle so step_open_store can take exclusive
        # ownership of the DuckDB. Reopened lazily after the Pipeline returns.
        if self._store is not None:
            self._store.close()
            self._store = None
        self._ctx.store = None

        initial = PipelineState(
            run_id=run_id,
            data={
                "ctx": self._ctx,
                "cfg": self.cfg,
                "config_path": self._config_path,
                "raw_toml": getattr(self._ctx, "raw_toml", {}) or {},
                "skip_display": skip_display,
                "spatial_support_registry": self._spatial_support_registry,
                "requested_spatial_support_ids": self._requested_support_ids,
                "requested_domain_supports": self._requested_domain_supports,
            },
        )

        pipeline = Pipeline(steps, workspace=workspace_path, checkpoint=checkpoint)
        try:
            final = pipeline.run(initial, resume_from=resume_from)
        finally:
            self._open_catalog()

        final_ctx = final.get("ctx") if final is not None else None
        sim_id = getattr(final_ctx, "sim_id", None) if final_ctx is not None else None
        if sim_id is None or self._store is None:
            return None
        return self._store[sim_id]

    def _is_model_phase_ready(self) -> bool:
        """Return True when Project's eager init has produced the runtime objects."""
        setup = self._ctx.setup
        return (
            setup.workspace is not None
            and setup.geographic is not None
            and setup.domain is not None
        )

    def _resolve_workspace_path(self) -> Path:
        """Return the workspace root used to persist checkpoints and ledger."""
        workspace = self._ctx.setup.workspace
        if workspace is not None:
            return Path(workspace.root)
        if self._config_path is not None:
            return self._config_path.parent
        return Path.cwd()

    def sweep(
        self,
        parameters: dict[str, list[float] | dict],
        *,
        strategy: str = "enumerate",
        name_template: str = "{param}_{value:.4g}",
        parallel: int = 1,
    ):
        """Run N simulations from a parameter table.

        Strategies: ``enumerate`` (one-dimensional iteration, one run per
        value), ``grid`` (cartesian product). ``lhs`` and ``sobol`` are not
        implemented yet.
        """
        from hydromodpy.results.simulation_group import SimulationGroup
        from hydromodpy.workflow.parallel import run_sweep

        if parallel != 1:
            raise NotImplementedError("Parallel sweep requires worker pool setup")
        sim_ids = run_sweep(
            self,
            parameters=parameters,
            strategy=strategy,
            name_template=name_template,
        )
        return SimulationGroup(self._store, sim_ids)

    def overview(self, *, config_path: str | Path | None = None):
        """Generate the watershed identity card (data-only rapport).

        Today this delegates to :class:`DataOverviewLauncher`. The launcher
        will be fully folded into this method in a follow-up pass; the
        facade already gives programmatic callers a single entry point.
        """
        from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

        path = config_path if config_path is not None else self._config_path
        if path is None:
            raise ValueError("project.overview() requires a TOML path for now")
        return DataOverviewLauncher(path).run()

    def compare(self, *, config_path: str | Path | None = None):
        """Compare simulations as declared in a TOML config.

        Delegates to :class:`MethodComparisonLauncher`. Pairwise ad-hoc comparison
        stays available via the top-level :func:`hydromodpy.compare` shortcut.
        """
        from hydromodpy.analysis.comparison.orchestrator import MethodComparisonLauncher

        path = config_path if config_path is not None else self._config_path
        if path is None:
            raise ValueError("project.compare() requires a TOML path for now")
        return MethodComparisonLauncher(path).run()

    def batch(self, *, config_path: str | Path | None = None, **kwargs):
        """Run the regional-batch workflow. Delegates to :class:`RegionalLabLauncher`."""
        from hydromodpy.analysis.batch.runtime import RegionalLabLauncher

        path = config_path if config_path is not None else self._config_path
        if path is None:
            raise ValueError("project.batch() requires a TOML path for now")
        return RegionalLabLauncher(path).run(**kwargs)

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
          :func:`hydromodpy.calibration.cli.run_calibration_cli` with the
          given TOML path. Extra ``**kwargs`` are forwarded.
        * **Python mode** (``parameters`` supplied): build a
          :class:`CalibrationConfig` in memory from the declarations
          below and run the same loop. The project's own ``config_path``
          becomes the simulation TOML, so the caller does not need to
          point at a separate calibration TOML.

        Parameters
        ----------
        config_path
            Optional path to a calibration TOML. When omitted, the
            ``parameters`` / ``outputs`` / ``objective_blocks`` arguments
            describe the calibration in Python.
        parameters
            ``{name: decl}`` mapping; each decl is forwarded to
            :class:`~hydromodpy.calibration.config.CalibParameterDecl`
            (``bounds``, ``transform``, ``path``/``target``, ``mode``...).
        outputs
            ``{name: decl}`` mapping forwarded to
            :class:`~hydromodpy.calibration.config.CalibOutputDecl`.
        objective_blocks
            List of dicts forwarded to
            :class:`~hydromodpy.calibration.config.CalibObjectiveBlockDecl`.
        method, max_iter, save_runs, seed
            Top-level knobs on the Pydantic config.
        **kwargs
            Forwarded to the CLI in TOML mode, otherwise merged onto the
            in-memory Pydantic config.

        Returns
        -------
        CalibrationReport
            Structured session summary when called in Python mode.
            In TOML mode, returns whatever ``run_calibration_cli``
            returns (a dict by default, or a ``CalibrationReport`` when
            the caller passes ``return_report=True``).
        """
        if config_path is not None:
            from hydromodpy.calibration.cli import run_calibration_cli

            return run_calibration_cli(Path(config_path).expanduser().resolve(), **kwargs)

        if not parameters:
            raise ValueError(
                "Project.calibrate() requires either config_path= or "
                "parameters= (Python-mode declaration)."
            )
        if self._config_path is None:
            raise ValueError(
                "Python-mode calibrate requires Project to be loaded from a "
                "TOML path (need the simulation TOML on disk)."
            )

        from hydromodpy.calibration.cli import run_calibration_programmatic
        from hydromodpy.calibration.config import CalibrationConfig

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

    def simulate(
        self,
        *,
        time: tuple | None = None,
        processes: list | None = None,
        name: str | None = None,
        **overrides,
    ) -> Run:
        """Run one simulation with orchestration specified from Python.

        Equivalent to ``run()`` but lets the caller override the time window
        and the list of processes without touching the TOML. Useful when
        driving HydroModPy from a script where orchestration belongs in the
        Python code, not in the configuration file.

        Parameters
        ----------
        time : tuple, optional
            ``(start, end, step)`` triple, e.g. ``("2000-01-01",
            "2005-12-31", "1 month")``. Patches ``cfg.simulation.time``.
        processes : list, optional
            List of processes to run. Each entry is either a string
            (process type with the default solver) or a ``(type, solver)``
            tuple. Patches ``cfg.simulation.process``.
        name : str, optional
            Run name. Auto-generated if absent.
        **overrides
            Flow parameter overrides forwarded to :meth:`run`.
        """
        from hydromodpy.simulation.planning.config import (
            SimulationProcessConfig,
            SimulationTimeConfig,
        )

        if time is not None:
            start, end, step = time
            self.cfg.simulation.time = SimulationTimeConfig(
                start_datetime=start,
                end_datetime=end,
                step_value=step,
                coverage_policy=getattr(self.cfg.simulation.time, "coverage_policy", "warn"),
            )
            from hydromodpy.core.time import (
                apply_explicit_time_window_to_tgrids,
                require_flow_simulation_time_grid,
            )

            apply_explicit_time_window_to_tgrids(self.cfg)
            self._time_grid = require_flow_simulation_time_grid(self.cfg)
            self._ctx.setup.time_grid = self._time_grid

        if processes is not None:
            resolved: list[SimulationProcessConfig] = []
            for idx, entry in enumerate(processes):
                if isinstance(entry, str):
                    proc_type, solver_name = entry, self._solver
                else:
                    proc_type, solver_name = entry
                resolved.append(
                    SimulationProcessConfig(
                        id=f"{proc_type}_{idx}",
                        type=proc_type,
                        solvers=[solver_name],
                    )
                )
            self.cfg.simulation.process = resolved

        return self.run(name=name, **overrides)

    # -- Lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the SimulationCatalog and clean up preprocessing files."""
        from hydromodpy.spatial.geographic.store_ingestion import (
            cleanup_stable_folder,
        )

        cleanup_stable_folder(self.geographic)
        if self._store is not None:
            self._store.close()
            self._store = None

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
        runs = getattr(self, "_run_history", []) or []
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

    # -- Private -----------------------------------------------------------

    def _detect_solver(self) -> str:
        """Resolve the flow solver from the declared process list or solver block.

        Walks cfg.simulation.process for the first flow process, then falls
        back to cfg.solver.solver_engine (always set by Pydantic defaults).
        No silent override beyond that.
        """
        sim = self.cfg.simulation
        if sim.process:
            for proc in sim.process:
                if proc.type == "flow" and proc.solvers:
                    return proc.solvers[0]
        solver_cfg = getattr(self.cfg, "solver", None)
        engine = getattr(solver_cfg, "solver_engine", None) if solver_cfg else None
        if engine:
            return str(engine)
        raise ValueError(
            "No flow solver declared. Add a [[simulation.process]] entry with "
            "type='flow' or set [solver] solver_engine."
        )

    def _ensure_simulation_block(self) -> None:
        """Synthesize [simulation] from [data.recharge] when it is absent.

        Only used to accept TOMLs that declare data but no explicit orchestration.
        The synthesized block uses the recharge date window, monthly steps and the
        already-resolved solver. Errors out if date bounds are missing.
        """
        if self.cfg.simulation.has_processes():
            return

        from hydromodpy.simulation.planning.config import (
            SimulationConfig,
            SimulationProcessConfig,
            SimulationTimeConfig,
        )
        from hydromodpy.workflow.steps.plan_building import DEFAULT_FLOW_PROCESS_ID

        recharge_cfg = getattr(self.cfg.data, "recharge", None)
        start = getattr(recharge_cfg, "date_start", None) if recharge_cfg else None
        end = getattr(recharge_cfg, "date_end", None) if recharge_cfg else None
        if start is None or end is None:
            raise ValueError(
                "Simulation requires [simulation.time] or [data.recharge] with "
                "date_start/date_end to define the simulation window."
            )

        default_name = (
            re.sub(r"^run_", "", self._config_path.stem)
            if self._config_path is not None
            else "simulation"
        )
        self.cfg.simulation = SimulationConfig(
            name=default_name,
            time=SimulationTimeConfig(
                start_datetime=start,
                end_datetime=end,
            ),
            process=[
                SimulationProcessConfig(
                    id=DEFAULT_FLOW_PROCESS_ID,
                    type="flow",
                    solvers=[self._solver],
                )
            ],
        )


class _ProjectDataAccessor:
    """Helper exposed as ``project.data``.

    Lists input-data cache entries used by the project, locates a specific
    :class:`~hydromodpy.data.entry.DataEntry`, and reports missing variables.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def list(self, variable: str | None = None):
        import pandas as pd

        loaded = self._project.data_loaded
        if variable is not None:
            loaded = {v for v in loaded if v == variable}
        return pd.DataFrame({"variable": sorted(loaded)})

    def missing(self) -> list[str]:
        plan_types = getattr(self._project._ctx.data_plan, "types", ()) or ()
        loaded = self._project.data_loaded
        return [t for t in plan_types if t not in loaded]


class _ProjectRunsAccessor:
    """Helper exposed as ``project.runs``.

    Thin wrapper around :class:`~hydromodpy.results.catalog.SimulationCatalog`
    that pre-filters queries by the current project name.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def list(self):
        store = self._project._store
        if store is None:
            import pandas as pd

            return pd.DataFrame()
        return store.list_simulations(project=self._project._project_name)

    def find(self, **filters):
        store = self._project._store
        if store is None:
            return []
        return store.find(project=self._project._project_name, **filters)

    def latest(self):
        df = self.list()
        if df.empty:
            return None
        return self._project._store[df.iloc[-1]["sim_id"]]

    def best(self, metric: str):
        store = self._project._store
        if store is None:
            return None
        return store.best(self._project._project_name, metric=metric)
