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
# Project
# =====================================================================

class Project:
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

    Examples
    --------
    ::

        import hydromodpy as hmp

        project = hmp.Project("project.toml")

        # Simple run
        r = project.run(Sy=0.05)

        # Parameter sweep
        for sy in [0.001, 0.05, 0.30]:
            r = project.run(Sy=sy, name=f"sy_{sy:.4f}")
            print(r.timeseries("outflow_drain").mean())

        project.close()
    """

    def __init__(self, config_path: str | Path, *, solver: str | None = None) -> None:
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.core.config.toml_loader import load_toml_with_base_config
        from hydromodpy.core.state.run_state import LauncherRunState
        from hydromodpy.core.time import (
            apply_explicit_time_window_to_tgrids,
            require_flow_simulation_time_grid,
        )
        from hydromodpy.data import DataManagersPlanner
        from hydromodpy.results.store import ResultStore
        from hydromodpy.spatial.geographic.store_ingestion import (
            cleanup_stable_folder,
            persist_geographic_to_store,
        )

        self._config_path = Path(config_path).resolve()

        # Phase 1: config
        self.cfg = HydroModPyConfig.from_toml(self._config_path)
        raw_toml = load_toml_with_base_config(self._config_path)

        self._solver = solver or self._detect_solver()
        self._ensure_simulation_block()

        # Phase 2: time grid
        apply_explicit_time_window_to_tgrids(self.cfg)
        self._time_grid = require_flow_simulation_time_grid(self.cfg)

        # Phase 3: data plan
        data_plan = DataManagersPlanner().build(
            self.cfg.data,
            domain_zone_ids=self.cfg.domain.zone_ids,
            raw_toml=raw_toml,
            flow_active_bc=self.cfg.flow.active_bc,
        )
        self.cfg.data = self.cfg.data.with_resolved_types(data_plan.types)

        # Build runtime state
        self._run_state = LauncherRunState(
            cfg=self.cfg,
            config_path=self._config_path,
            raw_toml=raw_toml,
        )
        self._run_state.data_plan = data_plan
        self._run_state.setup.time_grid = self._time_grid

        # Phase 4: setup (workspace, geographic, domain, flow, transport)
        from hydromodpy.workflow.steps.setup import step_setup
        step_setup(self._run_state)

        # Phase 5: data loading + structural bindings
        from hydromodpy.workflow.steps.data_loading import step_data_loading
        step_data_loading(self._run_state)

        # Open store (stays open for project lifetime)
        ws = self._run_state.setup.workspace
        self._store = ResultStore(
            project_path=ws.project_root,
            workspace_path=getattr(ws, "workspace_root", None),
        )
        persist_geographic_to_store(self.geographic, self._store)
        cleanup_stable_folder(self.geographic)

        self._run_counter = 0
        logger.info("Project ready: %s", self._config_path.name)

    # -- Public properties -------------------------------------------------

    @property
    def geographic(self):
        """Geographic runtime object (DEM, watershed, CRS)."""
        return self._run_state.setup.geographic

    @property
    def domain(self):
        """Spatial domain (mesh, layers, zones)."""
        return self._run_state.setup.domain

    @property
    def store(self):
        """Open ResultStore for direct queries across all runs."""
        return self._store

    @property
    def time_grid(self):
        """Resolved simulation time grid."""
        return self._time_grid

    @property
    def data(self):
        """Loaded data context (recharge, geology, hydrometry, etc.)."""
        return self._run_state.loaded_data

    # -- Run ---------------------------------------------------------------

    def run(self, *, name: str | None = None, **overrides) -> SimulationResult:
        """Execute one simulation with optional parameter overrides.

        Parameters
        ----------
        name : str, optional
            Run name. Auto-generated if absent.
        **overrides
            Flow parameter overrides (``Sy``, ``K``, ``Ss``).
            Special keys: ``thickness`` (domain depth), ``first_clim``
            (recharge start mode).

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
        from hydromodpy.simulation.results.post_run import post_run_results
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

        # Fresh Flow from config + overrides
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

        # Apply recharge binding
        window = self._time_grid.window if self._time_grid else None
        if window is not None and self._run_state.loaded_data.recharge is not None:
            apply_recharge_load_result_to_flow(
                flow=flow,
                recharge_result=self._run_state.loaded_data.recharge,
                simulation_window=window,
            )

        # Domain (optionally with new thickness)
        domain = self._run_state.setup.domain
        if thickness is not None:
            domain = self._rebuild_domain(thickness)

        # Inject into run_state
        self._run_state.setup.flow = flow
        self._run_state.setup.run_id = name
        original_domain = self._run_state.setup.domain
        self._run_state.setup.domain = domain

        # Minimal plan: single flow run
        run_entry = ProcessRun(
            id=f"flow_main::{self._solver}",
            process_id="flow_main",
            process_type="flow",
            solver=self._solver,
        )
        plan = SimulationPlan(name=name, description=name, runs=(run_entry,))
        self._run_state.execution.simulation_plan = plan
        self._run_state.execution.process_runs_by_id = {run_entry.id: run_entry}

        # Register in store (replaces existing with same name)
        self._store.register_simulation(
            sim_id, name=name, solver=self._solver, run_id=name,
        )

        # Execute
        solver_dir = [None]

        def _after_run(run, result, state):
            solver_dir[0] = result.solver_output_dir

        try:
            SimulationRunner(
                callbacks=ProcessCallbacks(after_run=_after_run),
            ).execute(plan, self._run_state)
        finally:
            self._run_state.setup.domain = original_domain

        # Ingest results
        results_cfg = ResultsConfig(
            keep_solver_files=True,
            budget=BudgetConfig(spatial_fields=True),
            derived=DerivedConfig(accumulation_flux=True, outflow_drain=True),
            export=ExportConfig(csv_timeseries=True, netcdf=False),
        )
        post_run_results(
            sim_id=sim_id,
            solver_name=self._solver,
            solver_output_dir=solver_dir[0],
            results_config=results_cfg,
            store=self._store,
            keep_solver_files=True,
            run_id=name,
        )
        self._store.finalize(sim_id, status="completed")

        logger.info("Run '%s' completed", name)
        return SimulationResult(sim_id=sim_id, name=name, store=self._store)

    # -- Lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the ResultStore."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self) -> str:
        return f"Project({self._config_path.name!r})"

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
                "Project requires [simulation.time] or [data.recharge] with "
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
        surface_topo = self._run_state.setup.geographic_features.surface_topo
        domain = Domain(config=domain_cfg, surface_topo=surface_topo)
        apply_catchment_zones_to_domain(
            domain=domain,
            geographic=self._run_state.setup.domain_geographic,
        )
        if self._run_state.loaded_data.geology is not None:
            apply_geology_to_domain(
                domain=domain,
                geology=self._run_state.loaded_data.geology,
            )
        return domain
