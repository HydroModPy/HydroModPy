"""HydroModPy launcher driven by an explicit simulation plan.

This module is the user-facing entry point that turns a declarative TOML file
into a concrete modeling run.  The launcher is a thin shell: it loads and
validates configuration, then delegates all business logic to the
``hydromodpy.workflow`` layer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.spatial.domain.spatial_support import (
    build_default_spatial_support_provider_registry,
)
from hydromodpy.analysis.postprocess.runner import PostprocessRunner
from hydromodpy.simulation import SimulationPlanner
from hydromodpy.core.state.run_state import LauncherRunState
from hydromodpy.workflow.context import WorkflowContext
from hydromodpy.core.time import (
    apply_explicit_time_window_to_tgrids,
    require_flow_simulation_time_grid,
)
from hydromodpy.spatial.mesh.runtime import (
    prepare_geographic_config_for_meshing,
)

# Workflow steps (canonical source of truth) --------------------------------
from hydromodpy.workflow.steps.setup import (
    collect_requested_support_ids,
    support_provider_names,
    resolve_support_configs,
)
from hydromodpy.workflow.steps.data_loading import log_data_plan
from hydromodpy.workflow.steps.mesh import (
    resolve_optional_mesh_section,
    resolve_optional_mesh_input,
)

if TYPE_CHECKING:
    from hydromodpy.data import DataLoadPlan
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfigSchema

logger = logging.getLogger(__name__)


def _build_data_plan(*args, **kwargs):
    """Import planner lazily to keep launcher imports lightweight in tests."""
    from hydromodpy.data import DataManagersPlanner

    return DataManagersPlanner().build(*args, **kwargs)


class HydroModPyLauncher:
    """Thin shell: TOML → WorkflowContext → pipeline → results.

    Example
    -------
    >>> launcher = HydroModPyLauncher(Path("config.toml"))
    >>> run_state = launcher.run()
    """

    model_calibration_runtime_direct = True
    model_calibration_runtime_reusable = True

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        apply_explicit_time_window_to_tgrids(self.cfg)
        self.time_grid = require_flow_simulation_time_grid(self.cfg)

        raw_toml = load_toml_with_base_config(self.config_path)
        self.mesh_section_data = resolve_optional_mesh_section(raw_toml)
        self.external_mesh_input = resolve_optional_mesh_input(
            raw_toml, self.config_path,
        )
        self.mesh_constraints_mode = None
        if self.mesh_section_data is not None and self.external_mesh_input is not None:
            raise ValueError(
                "Embedded [mesh_catchment] and external [mesh_input] are mutually "
                "exclusive in process_simulation. Use only one mesh source."
            )
        if self.mesh_section_data is not None:
            self.mesh_constraints_mode = self.mesh_section_data.constraints_mode
            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode=self.mesh_constraints_mode,
            )
        elif (
            self.external_mesh_input is not None
            and "stream"
            in {
                str(bc_id).strip().lower()
                for bc_id in getattr(self.cfg.flow, "active_bc", ())
            }
        ):
            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode="rivers_only",
                section_name="mesh_input",
            )

        self.spatial_support_provider_registry = (
            build_default_spatial_support_provider_registry()
        )
        self.requested_spatial_support_ids = collect_requested_support_ids(
            self.cfg.flow,
        )
        self.requested_domain_supports = resolve_support_configs(
            self.cfg.domain, self.requested_spatial_support_ids,
        )

        data_plan = _build_data_plan(
            self.cfg.data,
            domain_zone_ids=self.cfg.domain.zone_ids,
            domain_support_provider_names=support_provider_names(
                self.requested_domain_supports,
            ),
            requested_spatial_support_ids=self.requested_spatial_support_ids,
            raw_toml=raw_toml,
            flow_active_bc=self.cfg.flow.active_bc,
        )
        log_data_plan(data_plan)
        self.cfg.data = self.cfg.data.with_resolved_types(data_plan.types)
        self.data_plan = data_plan

        self.run_state = WorkflowContext(
            cfg=self.cfg,
            config_path=self.config_path,
            raw_toml=raw_toml,
        )
        self.run_state.setup.time_grid = self.time_grid
        self.run_state.data_plan = data_plan
        self.postprocess_runner = PostprocessRunner(self.cfg.postprocess)
        self.run_state.postprocess_runner = self.postprocess_runner
        self._result_store = None
        self._sim_id = None
        self._prepared_runtime_plan = None
        self._prepared_runtime_ready = False

    # ------------------------------------------------------------------
    # Main run orchestration
    # ------------------------------------------------------------------

    def prepare_runtime(self):
        """Prepare the shared runtime once and cache the resolved execution plan."""
        if self._prepared_runtime_ready and self._prepared_runtime_plan is not None:
            return self._prepared_runtime_plan
        if not self.cfg.simulation.has_processes():
            raise ValueError(
                "Launchers require an explicit [simulation] block with at least "
                "one [[simulation.process]] entry."
            )

        run_state = self.run_state
        execution_state = run_state.execution
        plan = self._create_simulation_plan()
        self._validate_runtime_mesh_solver_compatibility(plan)
        execution_state.simulation_plan = plan
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}

        from hydromodpy.workflow.pipelines.simulation import (
            prepare_simulation_runtime,
        )

        prepare_simulation_runtime(
            run_state,
            mesh_section_data=self.mesh_section_data,
            constraints_mode=self.mesh_constraints_mode,
            external_mesh_input=self.external_mesh_input,
            requested_domain_supports=self.requested_domain_supports,
            spatial_support_registry=self.spatial_support_provider_registry,
            requested_spatial_support_ids=self.requested_spatial_support_ids,
        )

        self._prepared_runtime_plan = plan
        self._prepared_runtime_ready = True
        return plan

    def run_prepared(self) -> WorkflowContext:
        """Execute the cached runtime state after resetting only execution outputs."""
        plan = self.prepare_runtime()
        run_state = self.run_state
        execution_state = run_state.execution
        execution_state.simulation_plan = plan
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}
        execution_state.models_by_run_id = {}

        from hydromodpy.workflow.pipelines.simulation import execute_simulation

        execute_simulation(
            run_state,
            after_process=self._on_after_process,
        )

        self._result_store = run_state.store
        self._sim_id = run_state.sim_id
        return run_state

    def run(self) -> WorkflowContext:
        """Execute one full launcher session and return the populated runtime state."""
        return self.run_prepared()

    # ------------------------------------------------------------------
    # Launcher-specific helpers (not in workflow layer)
    # ------------------------------------------------------------------

    def _validate_runtime_mesh_solver_compatibility(self, plan) -> None:
        """Reject unsupported flow solvers when the launcher injects a Gmsh mesh."""
        if self.mesh_section_data is None and self.external_mesh_input is None:
            return

        uses_modflow_nwt = any(
            getattr(run, "process_type", None) == "flow"
            and str(getattr(run, "solver", "")).strip().lower() == "modflownwt"
            for run in getattr(plan, "runs", ())
        )
        if not uses_modflow_nwt:
            return

        mesh_source = "[mesh_input]" if self.external_mesh_input is not None else "[mesh_catchment]"
        raise ValueError(
            f"{mesh_source} provides a runtime Gmsh mesh in process_simulation, "
            "but flow solver 'modflownwt' still supports only the structured "
            "sgrid backend. Use 'modflow6' (or 'boussinesq') with the same "
            f"{mesh_source} block, or remove {mesh_source} and configure "
            "[modflownwt.sgrid.planar] instead."
        )

    def _create_simulation_plan(self):
        """Resolve the declarative ``[simulation]`` block into concrete runs."""
        planner = SimulationPlanner()
        return planner.build(self.cfg.simulation)

    def _on_after_process(self, process_type: str) -> None:
        """Run launcher-level actions after one process-family block."""
        self.postprocess_runner.after_process(process_type, self.run_state)

