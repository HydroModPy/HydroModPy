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
    ) -> None:
        """Build a Project from a TOML path or a HydroModPyConfig instance.

        Parameters
        ----------
        config : str | Path | HydroModPyConfig
            Either a path to a TOML file (supports ``base_config`` inheritance)
            or a fully-built ``HydroModPyConfig`` for fully-Python workflows.
        """
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.core.config.toml_loader import load_toml_with_base_config
        from hydromodpy.core.time import (
            apply_explicit_time_window_to_tgrids,
            require_flow_simulation_time_grid,
        )
        from hydromodpy.data import DataPlanner
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.spatial.domain.spatial_support import (
            build_default_spatial_support_provider_registry,
        )
        from hydromodpy.workflow.context import WorkflowContext
        from hydromodpy.workflow.pipeline import prepare_runtime
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

        # Phase 1: config — accept either a TOML path or a HydroModPyConfig.
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

        # Phase 2: time grid
        apply_explicit_time_window_to_tgrids(self.cfg)
        self._time_grid = require_flow_simulation_time_grid(self.cfg)

        # Phase 3: mesh section detection (only from TOML; skipped when
        # building from an in-memory HydroModPyConfig).
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

        # Phase 4: spatial supports
        self._spatial_support_registry = build_default_spatial_support_provider_registry()
        self._requested_support_ids = collect_requested_support_ids(self.cfg.flow)
        self._requested_domain_supports = resolve_support_configs(
            self.cfg.domain,
            self._requested_support_ids,
        )

        # Phase 5: data plan (enriched with domain supports)
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

        # Phase 6: build workflow context + run preparation pipeline.
        # In-memory configs use the current working directory as the
        # anchor for resolving relative data paths.
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

        prepare_runtime(
            self._ctx,
            mesh_section_data=self._mesh_section_data,
            constraints_mode=self._mesh_constraints_mode,
            external_mesh_input=self._external_mesh_input,
            requested_domain_supports=self._requested_domain_supports,
            spatial_support_registry=self._spatial_support_registry,
            requested_spatial_support_ids=self._requested_support_ids,
        )

        # Open catalog (stays open for project lifetime)
        ws = self._ctx.setup.workspace
        self._store = SimulationCatalog(ws.root)
        self._project_name = ws.project_root.name

        self._run_counter = 0
        self._active_runs: dict[str, str] = {}
        self._last_wall_seconds: dict[str, float] = {}
        source = self._config_path.name if self._config_path else "<in-memory config>"
        logger.info("Project ready: %s", source)

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
    def data(self):
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
        from hydromodpy.workflow.pipeline import prepare_run

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
        from hydromodpy.workflow.pipeline import execute_run

        final_name = self._active_runs.get(sim_id, self._ctx.setup.run_id)
        wall = execute_run(self._ctx, sim_id, final_name=final_name)
        self._last_wall_seconds[sim_id] = wall
        return wall

    def ingest(self, sim_id: str, *, extractors: list[str] | None = None) -> None:
        """Ingest observations for a completed simulation."""
        from hydromodpy.workflow.pipeline import ingest_run

        ingest_run(self._ctx, sim_id, extractors=extractors)

    def render(
        self,
        sim_id: str,
        *,
        figures: list[str] | None = None,
    ) -> list[Path]:
        """Render the display figures attached to this simulation."""
        from hydromodpy.workflow.pipeline import render_run

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
        from hydromodpy.workflow.pipeline import cleanup_run

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

    def run(self, *, name: str | None = None, **overrides) -> Run:
        """Prepare, execute, ingest, render and clean up in one call.

        Flow parameter overrides (``Sy``, ``K``, ``Ss``) and the special keys
        ``thickness``, ``first_clim``, ``properties`` are forwarded to
        :meth:`prepare`. Returns the persisted :class:`Run` view.
        """
        sim_id = self.prepare(name=name, **overrides)
        try:
            self.execute(sim_id)
            self.ingest(sim_id)
            self.render(sim_id)
        except Exception:
            self.cleanup(sim_id, status="failed")
            raise
        self.cleanup(sim_id)
        return self._store[sim_id]

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
