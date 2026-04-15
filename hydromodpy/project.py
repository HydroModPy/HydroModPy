"""High-level Simulation API for interactive Python usage.

Setup-once, run-many interface that wraps the launcher's internal phases
behind a clean API.  The TOML-driven workflow (``hmp run``) is unchanged;
this module provides the **programmatic** equivalent.

Example
-------
::

    import hydromodpy as hmp

    project = hmp.Simulation("project.toml")

    result = project.run(Sy=0.05, K=5e-5, name="baseline")
    wt = result.field("watertable_depth", timestep=12)
    ts = result.timeseries("outflow_drain")

    project.close()
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# =====================================================================
# SimulationResult
# =====================================================================

class SimulationResult:
    """Read-only view on one simulation's results in the project store.

    Attributes
    ----------
    sim_id : str
        UUID of the simulation.
    name : str
        Human-readable run name.
    """

    def __init__(self, sim_id: str, name: str, store: Any) -> None:
        self.sim_id = sim_id
        self.name = name
        self._store = store

    def field(
        self,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        """Load a spatial field for one timestep.

        Supports stored variables (head, budget), derived variables
        (watertable_depth, seepage_areas, accumulation_flux), and
        virtual fields (outflow_drain).
        """
        return self._store.query_field(self.sim_id, variable, timestep, layer=layer)

    def timeseries(
        self,
        variable: str,
        station: str = "_catchment",
        period: tuple | None = None,
    ) -> pd.Series:
        """Load a time series from the store.

        Parameters
        ----------
        variable : str
            E.g. ``"outflow_drain"``, ``"watertable_depth"``.
        station : str
            Defaults to ``"_catchment"`` (catchment-wide aggregate).
        """
        return self._store.query_timeseries(
            self.sim_id, station, variable, period=period,
        )

    def budget(
        self,
        zone_id: int | None = None,
        period: tuple | None = None,
    ) -> pd.DataFrame:
        """Load budget records."""
        return self._store.query_budget(self.sim_id, zone_id=zone_id, period=period)

    def export(
        self,
        variable: str = "*",
        fmt: str = "csv",
        path: str | Path | None = None,
        **kwargs,
    ) -> None:
        """Export results to a file.

        Parameters
        ----------
        variable : str
            Variable name or ``"*"`` for all timeseries.
        fmt : str
            ``"csv"``, ``"netcdf"``, ``"geotiff"``, ``"vtu"``, ``"shapefile"``.
        path : Path, optional
            Output file path.  Defaults to ``exports/<name>/<variable>.<ext>``.
        """
        if path is None:
            ext_map = {"csv": "csv", "netcdf": "nc", "vtu": "vtu",
                       "geotiff": "tif", "shapefile": "shp"}
            ext = ext_map.get(fmt, fmt)
            out_dir = self._store.project_path / "exports" / self.name
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{variable}.{ext}" if variable != "*" else out_dir / f"timeseries.{ext}"
        self._store.export(self.sim_id, variable, fmt, path, **kwargs)

    def __repr__(self) -> str:
        return f"SimulationResult({self.name!r})"


# =====================================================================
# Simulation
# =====================================================================

class Simulation:
    """Setup-once, run-many interface for HydroModPy simulations.

    Loads a project TOML, builds the geographic/domain/data context once,
    then allows running multiple simulations with parameter overrides.

    Parameters
    ----------
    config_path : str or Path
        Path to the project TOML file.
    solver : str, optional
        Flow solver name.  Auto-detected from the TOML, defaults to
        ``"modflownwt"``.
    headless : bool, optional
        Disable display and postprocess runners (useful for calibration
        loops where generating figures per iteration is wasteful).

    Examples
    --------
    ::

        import hydromodpy as hmp

        project = hmp.Simulation("project.toml")

        # Simple run
        r = project.run(Sy=0.05)

        # Parameter sweep
        for sy in [0.001, 0.05, 0.30]:
            r = project.run(Sy=sy, name=f"sy_{sy:.4f}")
            print(r.timeseries("outflow_drain").mean())

        project.close()
    """

    def __init__(
        self,
        config_path: str | Path,
        *,
        solver: str | None = None,
        headless: bool = False,
    ) -> None:
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.core.config.toml_loader import load_toml_with_base_config
        from hydromodpy.core.time import (
            apply_explicit_time_window_to_tgrids,
            require_flow_simulation_time_grid,
        )
        from hydromodpy.data import DataManagersPlanner
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.spatial.domain.spatial_support import (
            build_default_spatial_support_provider_registry,
        )
        from hydromodpy.analysis.postprocess.runner import PostprocessRunner
        from hydromodpy.workflow.context import WorkflowContext
        from hydromodpy.workflow.pipelines.simulation import (
            prepare_simulation_runtime,
        )
        from hydromodpy.workflow.steps.setup import (
            collect_requested_support_ids,
            support_provider_names,
            resolve_support_configs,
        )
        from hydromodpy.workflow.steps.mesh import (
            resolve_optional_mesh_section,
            resolve_optional_mesh_input,
        )
        from hydromodpy.workflow.steps.data_loading import log_data_plan

        self._config_path = Path(config_path).resolve()

        # Phase 1: config
        self.cfg = HydroModPyConfig.from_toml(self._config_path)
        raw_toml = load_toml_with_base_config(self._config_path)

        self._solver = solver or self._detect_solver()
        self._ensure_simulation_block()

        # Phase 2: time grid
        apply_explicit_time_window_to_tgrids(self.cfg)
        self._time_grid = require_flow_simulation_time_grid(self.cfg)

        # Phase 3: mesh section detection
        self._mesh_section_data = resolve_optional_mesh_section(raw_toml)
        self._external_mesh_input = resolve_optional_mesh_input(
            raw_toml, self._config_path,
        )
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
        elif (
            self._external_mesh_input is not None
            and "stream"
            in {
                str(bc_id).strip().lower()
                for bc_id in getattr(self.cfg.flow, "active_bc", ())
            }
        ):
            from hydromodpy.spatial.mesh.runtime import (
                prepare_geographic_config_for_meshing,
            )
            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode="rivers_only",
                section_name="mesh_input",
            )

        # Phase 4: spatial supports
        self._spatial_support_registry = (
            build_default_spatial_support_provider_registry()
        )
        self._requested_support_ids = collect_requested_support_ids(self.cfg.flow)
        self._requested_domain_supports = resolve_support_configs(
            self.cfg.domain, self._requested_support_ids,
        )

        # Phase 5: data plan (enriched with domain supports)
        data_plan = DataManagersPlanner().build(
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

        # Phase 6: build workflow context + run preparation pipeline
        self._ctx = WorkflowContext(
            cfg=self.cfg,
            config_path=self._config_path,
            raw_toml=raw_toml,
        )
        self._ctx.data_plan = data_plan
        self._ctx.setup.time_grid = self._time_grid

        # Phase 7: postprocess runner
        self._headless = headless
        if headless:
            self.cfg.display.enabled = False
            self.cfg.display.show = False
            self.cfg.display.save = False
            self.cfg.postprocess.enabled = False
        self._postprocess_runner = PostprocessRunner(self.cfg.postprocess)
        self._ctx.postprocess_runner = self._postprocess_runner

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
        workspace_root = getattr(ws, "workspace_root", None) or ws.project_root
        self._store = SimulationCatalog(workspace_root)
        self._project_name = ws.project_root.name

        self._run_counter = 0
        logger.info("Simulation ready: %s", self._config_path.name)

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

    def run(self, *, name: str | None = None, **overrides) -> SimulationResult:
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
        SimulationResult
        """
        from hydromodpy.process.flow import Flow
        from hydromodpy.process.flow.structure_binders import (
            apply_recharge_load_result_to_flow,
        )
        from hydromodpy.simulation.execution.runner import (
            ProcessCallbacks,
            SimulationRunner,
        )
        from hydromodpy.simulation.planning.plan import (
            ProcessRun,
            SimulationPlan,
        )
        from hydromodpy.simulation import SimulationPlanner
        from hydromodpy.simulation.results.post_run import post_run_results
        from hydromodpy.spatial.geographic.store_ingestion import (
            persist_geographic_to_store,
        )
        from hydromodpy.results.config import (
            BudgetConfig,
            DerivedConfig,
            ExportConfig,
            ResultsConfig,
        )

        self._run_counter += 1
        sim_id = str(uuid4())
        if name is None:
            name = f"run_{self._run_counter:04d}"

        # Special overrides
        thickness = overrides.pop("thickness", None)
        first_clim = overrides.pop("first_clim", None)
        properties = overrides.pop("properties", None)

        if overrides or thickness is not None or first_clim is not None:
            plan = self._run_with_overrides(
                name, overrides, thickness=thickness, first_clim=first_clim,
            )
        else:
            plan = self._run_from_plan(name)

        # Inject spatially varying property arrays (calibration use-case)
        if properties is not None:
            self._ctx.setup.flow_runtime_overrides = {
                "source": "project_run",
                "properties": dict(properties),
            }
        else:
            self._ctx.setup.flow_runtime_overrides = None

        # Register in catalog with enriched metadata
        solvers = ",".join(r.solver for r in plan.runs)
        reg_kwargs: dict = {
            "flow_regime": self.cfg.flow.flow_regime,
        }
        try:
            reg_kwargs["config"] = self.cfg.model_dump(mode="json")
        except Exception:
            pass

        mesh = self._ctx.setup.mesh_planar
        if mesh is not None:
            reg_kwargs["n_cells"] = mesh.n_cells
            reg_kwargs["mesh_type"] = getattr(mesh, "cell_type", None)
            reg_kwargs["cell_types"] = [getattr(mesh, "cell_type", "unknown")]
            bbox = getattr(mesh, "bounds", None)
            if bbox is not None:
                reg_kwargs["bbox"] = list(bbox)
            try:
                import hashlib as _hashlib
                mesh_bytes = mesh.points_xy.tobytes() + mesh.connectivity.tobytes()
                reg_kwargs["mesh_hash"] = _hashlib.sha256(mesh_bytes).hexdigest()
            except Exception:
                pass

        crs = getattr(self.cfg.geographic, "crs_project", None)
        if crs is not None:
            reg_kwargs["crs"] = str(crs)

        tg = self._ctx.setup.time_grid
        if tg is not None:
            boundaries = getattr(tg, "boundaries", None)
            if boundaries and len(boundaries) >= 2:
                reg_kwargs["period_start"] = str(boundaries[0])
                reg_kwargs["period_end"] = str(boundaries[-1])
                reg_kwargs["n_timesteps"] = len(boundaries) - 1
            time_cfg = getattr(self.cfg.simulation, "time", None)
            if time_cfg is not None:
                reg_kwargs["time_unit"] = getattr(time_cfg, "step_unit", None)

        self._store.register_simulation(
            sim_id, project=self._project_name, solver=solvers,
            name=name, run_id=name,
            **reg_kwargs,
        )

        # Write hydraulic parameters
        from hydromodpy.workflow.steps.store_lifecycle import _write_flow_parameters
        if self._ctx.setup.flow is not None:
            _write_flow_parameters(self._store, sim_id, self._ctx.setup.flow)

        # Write mesh topology into Zarr
        if mesh is not None:
            z_intf = None
            domain = self._ctx.setup.domain
            if domain is not None:
                z_intf_attr = getattr(domain, "z_interfaces", None)
                if z_intf_attr is not None:
                    z_intf = np.asarray(z_intf_attr)
            if z_intf is None:
                z_intf = np.array([0.0, -10.0])
            self._store.write_mesh(
                sim_id,
                vertices=mesh.points_xy,
                face_node_connectivity=mesh.connectivity,
                z_interfaces=z_intf,
            )

        # Persist geographic rasters into this simulation's Zarr
        if self.geographic is not None:
            persist_geographic_to_store(
                self.geographic, self._store,
                sim_id=sim_id,
            )

        # Persist input forcings for reproducibility
        from hydromodpy.workflow.steps.result_ingestion import step_persist_forcings
        _tmp_ctx = type("_Ctx", (), {
            "store": self._store,
            "sim_id": sim_id,
            "loaded_data": self._ctx.loaded_data,
            "setup": self._ctx.setup,
        })()
        step_persist_forcings(_tmp_ctx)

        # Wire store + sim_id into postprocess runner
        self._postprocess_runner.store = self._store
        self._postprocess_runner.sim_id = sim_id

        # Execute
        has_transport = any(r.process_type == "transport" for r in plan.runs)
        results_cfg = ResultsConfig(
            keep_solver_files=True,
            budget=BudgetConfig(spatial_fields=True),
            derived=DerivedConfig(
                accumulation_flux=True,
                outflow_drain=True,
                concentration_seepage=has_transport,
                mass_seepage=has_transport,
            ),
            export=ExportConfig(csv_timeseries=True, netcdf=False),
        )

        def _after_run(run, result, state):
            post_run_results(
                sim_id=sim_id,
                solver_name=run.solver,
                solver_output_dir=result.solver_output_dir,
                results_config=results_cfg,
                store=self._store,
                keep_solver_files=True,
                run_id=name,
            )

        def _after_process(process_type):
            self._postprocess_runner.after_process(process_type, self._ctx)

        original_domain = self._ctx.setup.domain
        try:
            SimulationRunner(
                callbacks=ProcessCallbacks(
                    after_run=_after_run,
                    after_process=_after_process,
                ),
            ).execute(plan, self._ctx)
        except Exception:
            self._store.finalize(sim_id, status="failed")
            raise
        finally:
            self._ctx.setup.domain = original_domain
            self._ctx.setup.flow_runtime_overrides = None

        self._store.finalize(sim_id, status="completed")

        logger.info("Run '%s' completed", name)
        return SimulationResult(sim_id=sim_id, name=name, store=self._store)

    def _run_with_overrides(self, name, overrides, *, thickness=None, first_clim=None):
        """Build a minimal plan with parameter overrides applied to a fresh Flow."""
        from hydromodpy.process.flow import Flow
        from hydromodpy.process.flow.structure_binders import (
            apply_recharge_load_result_to_flow,
        )
        from hydromodpy.simulation.planning.plan import (
            ProcessRun,
            SimulationPlan,
        )

        flow = Flow(config=self.cfg.flow)
        for key, value in overrides.items():
            if key not in flow.parameters:
                raise ValueError(
                    f"Unknown parameter '{key}'. "
                    f"Available: {', '.join(sorted(flow.parameters))}"
                )
            flow.parameters[key].value = value

        if first_clim is not None:
            recharge_ss = getattr(flow, "sinks_sources", {})
            if "recharge" in recharge_ss:
                recharge_ss["recharge"].first_clim = first_clim

        window = self._time_grid.window if self._time_grid else None
        if window is not None and self._ctx.loaded_data.recharge is not None:
            apply_recharge_load_result_to_flow(
                flow=flow,
                recharge_result=self._ctx.loaded_data.recharge,
                simulation_window=window,
            )

        domain = self._ctx.setup.domain
        if thickness is not None:
            domain = self._rebuild_domain(thickness)

        self._ctx.setup.flow = flow
        self._ctx.setup.run_id = name
        self._ctx.setup.domain = domain

        run_entry = ProcessRun(
            id=f"flow_main::{self._solver}",
            process_id="flow_main",
            process_type="flow",
            solver=self._solver,
        )
        plan = SimulationPlan(name=name, description=name, runs=(run_entry,))
        self._ctx.execution.simulation_plan = plan
        self._ctx.execution.process_runs_by_id = {run_entry.id: run_entry}
        return plan

    def _run_from_plan(self, name):
        """Build a full plan via SimulationPlanner (no overrides)."""
        from hydromodpy.simulation import SimulationPlanner

        plan = SimulationPlanner().build(self.cfg.simulation)
        self._ctx.setup.run_id = name
        self._ctx.execution.simulation_plan = plan
        self._ctx.execution.process_runs_by_id = {r.id: r for r in plan.runs}
        return plan

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
        return f"Simulation({self._config_path.name!r})"

    # -- Private -----------------------------------------------------------

    def _detect_solver(self) -> str:
        # Explicit solver in [[simulation.process]]
        sim = self.cfg.simulation
        if sim.process:
            for proc in sim.process:
                if proc.type == "flow" and proc.solvers:
                    return proc.solvers[0]
        # Infer from TOML sections present in the raw file
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

        self.cfg.simulation = SimulationConfig(
            name=re.sub(r"^run_", "", self._config_path.stem),
            time=SimulationTimeConfig(
                start_datetime=start,
                end_datetime=end,
                step_value="1 month",
                coverage_policy="warn",
            ),
            process=[SimulationProcessConfig(
                id="flow_main", type="flow", solvers=[self._solver],
            )],
        )

    def _rebuild_domain(self, thickness: float):
        from hydromodpy.spatial.domain import Domain
        from hydromodpy.spatial.geographic.structure_binders import (
            apply_catchment_zones_to_domain,
            apply_geology_to_domain,
        )

        domain_cfg = self.cfg.domain.model_copy(deep=True)
        domain_cfg.depth_model.thickness = thickness
        surface_topo = self._ctx.setup.geographic_features.surface_topo
        domain = Domain(config=domain_cfg, surface_topo=surface_topo)
        apply_catchment_zones_to_domain(
            domain=domain,
            geographic=self._ctx.setup.domain_geographic,
        )
        if self._ctx.loaded_data.geology is not None:
            apply_geology_to_domain(
                domain=domain,
                geology=self._ctx.loaded_data.geology,
            )
        return domain
