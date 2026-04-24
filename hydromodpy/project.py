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
        from hydromodpy.workflow.pipelines.simulation import (
            prepare_simulation_runtime,
        )
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

        prepare_simulation_runtime(
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

    def run(self, *, name: str | None = None, **overrides) -> Run:
        """Execute one simulation with optional parameter overrides.

        Without overrides, runs the TOML configuration as-is using the full
        ``SimulationPlanner`` (supports multi-process plans).  With overrides,
        builds a minimal single-flow plan and patches the Flow parameters.

        Parameters
        ----------
        name : str, optional
            Run name. Auto-generated if absent.
        **overrides
            Flow parameter overrides (``Sy``, ``K``, ``Ss``).
            Special keys: ``thickness`` (domain depth), ``first_clim``
            (recharge start mode), ``properties`` (dict of spatially
            varying property arrays, e.g. from calibration).

        Returns
        -------
        :class:`~hydromodpy.results.run.Run`
            Ready-to-query view exposing ``sim_id``, ``name``,
            ``timeseries``, ``parameters``, ``budget``, ``export``, the
            lazy catchment metrics (``saturated_fraction``,
            ``drainage_density`` …), and ``plot``.
        """
        from hydromodpy.simulation.execution.runner import (
            ProcessCallbacks,
            SimulationRunner,
        )
        from hydromodpy.simulation.extraction.post_run import post_run_results
        from hydromodpy.workflow.steps.cleanup import step_cleanup_scratch
        from hydromodpy.workflow.steps.figures import step_render_figures
        from hydromodpy.workflow.steps.observations import step_ingest_observations
        from hydromodpy.workflow.steps.persistence import (
            step_persist_geographic,
            step_persist_mesh,
            step_persist_params,
        )
        from hydromodpy.workflow.steps.plan_building import step_build_plan
        from hydromodpy.workflow.steps.registration import step_register_simulation
        from hydromodpy.workflow.steps.result_ingestion import step_persist_forcings
        from hydromodpy.workflow.steps.results_config import step_configure_results

        self._run_counter += 1
        sim_id = str(uuid4())
        if name is None:
            name = DEFAULT_RUN_NAME_TEMPLATE.format(counter=self._run_counter)

        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

        plan = step_build_plan(
            self._ctx,
            name=name,
            overrides=overrides,
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

        self._ctx.store = self._store
        self._ctx.sim_id = sim_id
        final_name = step_register_simulation(
            self._ctx,
            sim_id,
            plan=plan,
            project_name=self._project_name,
            name=name,
        )
        self._ctx.setup.run_id = final_name

        if self._ctx.setup.flow is not None:
            step_persist_params(
                self._store,
                sim_id,
                self._ctx.setup.flow,
                domain=self.cfg.domain,
            )
        step_persist_mesh(self._ctx, sim_id)
        step_persist_geographic(self._ctx, sim_id)
        step_persist_forcings(self._ctx)

        results_cfg = step_configure_results(self.cfg.simulation.results, plan)

        def _after_run(run, result, state):
            post_run_results(
                sim_id=sim_id,
                solver_name=run.solver,
                solver_output_dir=result.solver_output_dir,
                results_config=results_cfg,
                store=self._store,
                run_id=final_name,
            )

        original_domain = self._ctx.setup.domain
        try:
            SimulationRunner(
                callbacks=ProcessCallbacks(after_run=_after_run),
            ).execute(plan, self._ctx)
        except Exception:
            self._store.finalize(sim_id, status="failed")
            raise
        finally:
            self._ctx.setup.domain = original_domain
            self._ctx.setup.flow_runtime_overrides = None

        self._store.finalize(sim_id, status="completed")
        step_ingest_observations(self._ctx, sim_id)

        run = self._store[sim_id]
        step_render_figures(
            self._ctx,
            run,
            sim_id=sim_id,
            run_name=final_name,
            headless=self._headless,
            no_display=self._no_display,
        )
        step_cleanup_scratch(
            self._ctx,
            keep_solver_files=results_cfg.keep_solver_files,
        )
        return run

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
        # Explicit solver in [[simulation.process]]
        sim = self.cfg.simulation
        if sim.process:
            for proc in sim.process:
                if proc.type == "flow" and proc.solvers:
                    return proc.solvers[0]
        # Prefer the [solver] config block when present.
        solver_cfg = getattr(self.cfg, "solver", None)
        engine = getattr(solver_cfg, "solver_engine", None) if solver_cfg else None
        if engine:
            return str(engine)
        # Infer from TOML sections present in the raw file (TOML-backed only).
        if self._config_path is not None:
            from hydromodpy.core.config.toml_loader import load_toml_with_base_config

            raw = load_toml_with_base_config(self._config_path)
            if "modflownwt" in raw:
                return "modflownwt"
            if "modflow6" in raw:
                return "modflow6"
        return "modflownwt"

    def _ensure_simulation_block(self) -> None:
        """Synthesize a [simulation] block if the TOML doesn't have one."""
        if self.cfg.simulation.has_processes():
            return

        from hydromodpy.simulation.planning.config import (
            SimulationConfig,
            SimulationProcessConfig,
            SimulationTimeConfig,
        )

        # Infer time window from recharge dates
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
                step_value="1 month",
                coverage_policy="warn",
            ),
            process=[
                SimulationProcessConfig(
                    id="flow_main",
                    type="flow",
                    solvers=[self._solver],
                )
            ],
        )
