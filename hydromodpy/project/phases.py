"""Model-phase adapter verbs used by :class:`Project`.

Split from :mod:`hydromodpy.project.facade` so the facade keeps the
run/lifecycle API only.

Functions here mutate the :class:`Project` instance directly and call the
same ``workflow.steps`` helpers that the full Pipeline uses. They are not a
second execution engine; they only adapt the shared step logic to the
interactive phase verbs (``prepare`` and the per-phase builders).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project.facade import Project

logger = get_logger(__name__)


def configure(
    project: Project,
    config: str | Path | HydroModPyConfig,
    *,
    solver: str | None,
    headless: bool,
    no_display: bool,
) -> None:
    """Resolve the config, time grid and data plan, then build an empty ctx."""
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.time import (
        apply_explicit_time_window_to_tgrids,
        require_flow_simulation_time_grid,
    )
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.data import DataPlanner
    from hydromodpy.spatial.domain.spatial_support import (
        build_default_spatial_support_provider_registry,
    )
    from hydromodpy.workflow.context import WorkflowContext
    from hydromodpy.workflow.steps.data import log_data_plan
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
        project._config_path = None
        project._cfg = config
        raw_toml: dict = {}
    else:
        project._config_path = Path(config).resolve()
        project._cfg = HydroModPyConfig.from_toml(project._config_path)
        raw_toml = load_toml_with_base_config(project._config_path)

    project._solver = solver or detect_solver(project)
    ensure_simulation_block(project)

    apply_explicit_time_window_to_tgrids(project._cfg)
    project._time_grid = require_flow_simulation_time_grid(project._cfg)

    if project._config_path is not None:
        project._mesh_section_data = resolve_optional_mesh_section(raw_toml)
        project._external_mesh_input = resolve_optional_mesh_input(
            raw_toml,
            project._config_path,
        )
    else:
        project._mesh_section_data = project._cfg.mesh_catchment
        project._external_mesh_input = None
    project._mesh_constraints_mode = None
    if project._mesh_section_data is not None and project._external_mesh_input is not None:
        raise ConfigError(
            "Embedded [mesh_catchment] and external [mesh_input] are mutually "
            "exclusive. Use only one mesh source."
        )
    if project._mesh_section_data is not None:
        from hydromodpy.spatial.mesh.runtime import (
            prepare_geographic_config_for_meshing,
        )

        project._mesh_constraints_mode = project._mesh_section_data.constraints_mode
        project._cfg.geographic = prepare_geographic_config_for_meshing(
            project._cfg.geographic,
            constraints_mode=project._mesh_constraints_mode,
        )
    elif project._external_mesh_input is not None and "stream" in {
        str(bc_id).strip().lower() for bc_id in getattr(project._cfg.flow, "active_bc", ())
    }:
        from hydromodpy.spatial.mesh.runtime import (
            prepare_geographic_config_for_meshing,
        )

        project._cfg.geographic = prepare_geographic_config_for_meshing(
            project._cfg.geographic,
            constraints_mode="rivers_only",
            section_name="mesh_input",
        )

    project._spatial_support_registry = build_default_spatial_support_provider_registry()
    project._requested_support_ids = collect_requested_support_ids(project._cfg.flow)
    project._requested_domain_supports = resolve_support_configs(
        project._cfg.domain,
        project._requested_support_ids,
    )

    data_plan = DataPlanner().build(
        project._cfg.data,
        domain_zone_ids=project._cfg.domain.zone_ids,
        domain_support_provider_names=support_provider_names(
            project._requested_domain_supports,
        ),
        requested_spatial_support_ids=project._requested_support_ids,
        raw_toml=raw_toml,
        flow_active_bc=project._cfg.flow.active_bc,
    )
    log_data_plan(data_plan)
    project._cfg.data = project._cfg.data.with_resolved_types(data_plan.types)

    project._ctx = WorkflowContext(
        cfg=project._cfg,
        config_path=project._config_path or Path.cwd(),
        raw_toml=raw_toml,
    )
    project._ctx.data_plan = data_plan
    project._ctx.setup.time_grid = project._time_grid

    project._headless = headless
    project._no_display = no_display
    if headless:
        project._cfg.display.save = False
        project._cfg.display.show = False

    project._store = None
    project._project_name = None
    project._run_counter = 0
    project._active_runs = {}
    project._last_wall_seconds = {}
    project._phase = "uninitialized"
    project._data_loaded = set()
    project._run_history = []
    source = project._config_path.name if project._config_path else "<in-memory config>"
    logger.info("Project configured: %s", source)


def setup_workspace(project: Project) -> None:
    """Bootstrap shared runtime state for a Project session.

    Idempotent: calling twice resets workspace, geographic, domain, and process
    objects. Opens the catalog as a side effect so later run-phase methods can
    register simulations.
    """
    from hydromodpy.workflow.steps.setup import step_setup, step_spatial_supports

    step_setup(
        project._ctx,
        requested_spatial_support_ids=project._requested_support_ids,
        requested_domain_supports=project._requested_domain_supports,
    )
    step_spatial_supports(
        project._ctx,
        phase="setup",
        requested_domain_supports=project._requested_domain_supports,
        registry=project._spatial_support_registry,
    )
    project._phase = "setup_workspace"
    open_catalog(project)


def build_geographic(project: Project, *, reuse_dem: bool = False) -> None:
    """Expose the geographic/domain runtime as ready for later phases.

    Runs ``setup_workspace`` first when it has not happened yet. The heavy
    geographic/domain construction currently happens there because flow/data
    binders need those objects early. This verb records the public Project phase
    and invalidates downstream data/mesh state.
    """
    if project._phase == "uninitialized":
        with progress.phase("build_geographic"):
            setup_workspace(project)
    project._phase = "geographic"
    project._data_loaded.clear()
    project._ctx.loaded_data.loaded_plan_types = None
    project._ctx.setup.mesh_planar = None
    project._ctx.setup.mesh_bundle = None


def load_data(project: Project, *, types: list[str] | None = None) -> None:
    """Load the external forcings declared in [data]."""
    from hydromodpy.workflow.steps.data import step_data_loading
    from hydromodpy.workflow.steps.setup import step_spatial_supports

    if project._phase == "uninitialized":
        build_geographic(project)
    with progress.phase("load_data"):
        step_data_loading(project._ctx)
        step_spatial_supports(
            project._ctx,
            phase="data",
            requested_domain_supports=project._requested_domain_supports,
            registry=project._spatial_support_registry,
        )
    if types is None:
        project._data_loaded = set(getattr(project._ctx.data_plan, "types", ()))
    else:
        project._data_loaded.update(types)
    project._phase = "data"


def reload_data(project: Project, *, types: list[str]) -> None:
    """Reload a subset of data variables without touching the others."""
    load_data(project, types=list(types))


def rebuild_geographic(project: Project, *, reuse_dem: bool = False) -> None:
    """Rerun the geographic pipeline and invalidate the mesh."""
    # Drop the setup products so the pipeline re-runs the geographic step
    # instead of reusing the in-memory context.
    setup = project._ctx.setup
    setup.geographic = None
    setup.geographic_features = None
    setup.domain_geographic = None
    setup.domain = None
    build_geographic(project, reuse_dem=reuse_dem)


def build_mesh(project: Project, **overrides: object) -> None:
    """Build the catchment mesh from the current geographic context.

    ``overrides`` patch ``cfg.mesh_catchment`` before the mesh step runs.
    """
    from hydromodpy.workflow.steps.mesh import step_mesh, step_mesh_input

    if project._phase == "uninitialized":
        load_data(project)
    if overrides:
        from hydromodpy.spatial.mesh.config import MeshCatchmentConfig

        if project._cfg.mesh_catchment is None:
            project._cfg.mesh_catchment = MeshCatchmentConfig.model_validate(overrides)
        else:
            merged = {**project._cfg.mesh_catchment.model_dump(), **overrides}
            project._cfg.mesh_catchment = MeshCatchmentConfig.model_validate(merged)
    with progress.phase("build_mesh"):
        step_mesh(
            project._ctx,
            mesh_section_data=project._mesh_section_data,
            constraints_mode=project._mesh_constraints_mode,
        )
        step_mesh_input(project._ctx, external_mesh_input=project._external_mesh_input)
    project._phase = "mesh"


def open_catalog(project: Project) -> None:
    """Open the Catalog for this workspace (idempotent)."""
    from hydromodpy.results.catalog import Catalog

    if project._store is not None:
        return
    ws = project._ctx.setup.workspace
    if ws is None:
        return
    project._store = Catalog.from_workspace(ws)
    project._project_name = ws.project_root.name


def detect_solver(project: Project) -> str:
    """Resolve the flow solver from the declared process list or solver block."""
    sim = project._cfg.simulation
    if sim.process:
        for proc in sim.process:
            if proc.type == "flow" and proc.solvers:
                return proc.solvers[0]
        if all(proc.type == "mesh" for proc in sim.process):
            return "mesh"
    solver_cfg = getattr(project._cfg, "solver", None)
    engine = getattr(solver_cfg, "backend_name", None) if solver_cfg else None
    if engine:
        return str(engine)
    raise ConfigMissingError(
        "No flow solver declared. Add a [[simulation.process]] entry with "
        "type='flow' or set [solver.backend]."
    )


def ensure_simulation_block(project: Project) -> None:
    """Synthesize [simulation] from [data.recharge] when it is absent."""
    if project._cfg.simulation.has_processes():
        return

    from hydromodpy.simulation.planning.config import (
        FlowProcessConfig,
        SimulationConfig,
        SimulationTimeConfig,
    )
    from hydromodpy.workflow.steps.planning import DEFAULT_FLOW_PROCESS_ID

    recharge_cfg = getattr(project._cfg.data, "recharge", None)
    start = getattr(recharge_cfg, "date_start", None) if recharge_cfg else None
    end = getattr(recharge_cfg, "date_end", None) if recharge_cfg else None
    if start is None or end is None:
        raise ConfigMissingError(
            "Simulation requires [simulation.time] or [data.recharge] with "
            "date_start/date_end to define the simulation window."
        )

    default_name = (
        re.sub(r"^run_", "", project._config_path.stem)
        if project._config_path is not None
        else "simulation"
    )
    project._cfg.simulation = SimulationConfig(
        name=default_name,
        time=SimulationTimeConfig(
            start_datetime=start,
            end_datetime=end,
        ),
        process=[
            FlowProcessConfig(
                id=DEFAULT_FLOW_PROCESS_ID,
                solvers=[project._solver],
            )
        ],
    )
