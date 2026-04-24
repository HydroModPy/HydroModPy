"""Plan-building steps - build a SimulationPlan from config or overrides."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


DEFAULT_FLOW_PROCESS_ID = "flow_main"


def step_build_plan(
    ctx: WorkflowContext,
    *,
    name: str,
    overrides: dict[str, Any] | None = None,
    thickness: float | None = None,
    first_clim: str | None = None,
    solver: str | None = None,
) -> SimulationPlan:
    """Build the SimulationPlan to execute.

    When overrides, thickness or first_clim are provided, synthesize a minimal
    single-flow plan with patched Flow parameters. Otherwise delegate to
    SimulationPlanner using the declared simulation.process list. Sets
    ctx.setup.run_id, ctx.execution.simulation_plan and the process-run map.
    """
    if overrides or thickness is not None or first_clim is not None:
        return _build_plan_with_overrides(
            ctx,
            name=name,
            overrides=overrides or {},
            thickness=thickness,
            first_clim=first_clim,
            solver=solver,
        )
    return _build_plan_from_config(ctx, name=name)


def _build_plan_from_config(ctx: WorkflowContext, *, name: str) -> SimulationPlan:
    from hydromodpy.simulation import SimulationPlanner

    plan = SimulationPlanner().build(ctx.cfg.simulation)
    ctx.setup.run_id = name
    ctx.execution.simulation_plan = plan
    ctx.execution.process_runs_by_id = {r.id: r for r in plan.runs}
    return plan


def _build_plan_with_overrides(
    ctx: WorkflowContext,
    *,
    name: str,
    overrides: dict[str, Any],
    thickness: float | None,
    first_clim: str | None,
    solver: str | None,
) -> SimulationPlan:
    from hydromodpy.physics.flow import Flow
    from hydromodpy.physics.flow.structure_binders import (
        apply_recharge_load_result_to_flow,
    )
    from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan

    flow = Flow(config=ctx.cfg.flow)
    step_apply_flow_overrides(flow, overrides)

    if first_clim is not None:
        recharge_ss = getattr(flow, "sinks_sources", {})
        if "recharge" in recharge_ss:
            recharge_ss["recharge"].first_clim = first_clim

    time_grid = ctx.setup.time_grid
    window = time_grid.window if time_grid is not None else None
    if window is not None and ctx.loaded_data.recharge is not None:
        apply_recharge_load_result_to_flow(
            flow=flow,
            recharge_result=ctx.loaded_data.recharge,
            simulation_window=window,
        )

    domain = ctx.setup.domain
    if thickness is not None:
        domain = step_rebuild_domain(ctx, thickness=thickness)

    ctx.setup.flow = flow
    ctx.setup.run_id = name
    ctx.setup.domain = domain

    solver_name = solver or _default_flow_solver(ctx)
    run_entry = ProcessRun(
        id=ProcessRun.build_id(DEFAULT_FLOW_PROCESS_ID, solver_name),
        process_id=DEFAULT_FLOW_PROCESS_ID,
        process_type="flow",
        solver=solver_name,
    )
    plan = SimulationPlan(name=name, description=name, runs=(run_entry,))
    ctx.execution.simulation_plan = plan
    ctx.execution.process_runs_by_id = {run_entry.id: run_entry}
    return plan


def step_apply_flow_overrides(flow, overrides: dict[str, Any]) -> None:
    """Patch homogeneous flow parameters in-place.

    Raises ValueError if an override targets an unknown parameter, listing the
    available keys so calibration loops fail fast.
    """
    for key, value in overrides.items():
        if key not in flow.parameters:
            available = ", ".join(sorted(flow.parameters))
            raise ValueError(f"Unknown parameter '{key}'. Available: {available}")
        flow.parameters[key].value = value


def step_rebuild_domain(ctx: WorkflowContext, *, thickness: float) -> Domain:
    """Rebuild the Domain with a new aquifer thickness.

    Reapplies catchment zones and geology binders so the returned Domain is
    fully hydrated. Does not mutate ctx.setup.domain; the caller stores the
    result once the run consumes it.
    """
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.spatial.geographic.structure_binders import (
        apply_catchment_zones_to_domain,
        apply_geology_to_domain,
    )

    domain_cfg = ctx.cfg.domain.model_copy(deep=True)
    domain_cfg.depth_model.thickness = thickness
    surface_topo = ctx.setup.geographic_features.surface_topo
    domain = Domain(config=domain_cfg, surface_topo=surface_topo)
    apply_catchment_zones_to_domain(
        domain=domain,
        geographic=ctx.setup.domain_geographic,
    )
    if ctx.loaded_data.geology is not None:
        apply_geology_to_domain(
            domain=domain,
            geology=ctx.loaded_data.geology,
        )
    return domain


def _default_flow_solver(ctx: WorkflowContext) -> str:
    """Resolve the flow solver name from cfg.simulation.process."""
    for proc in ctx.cfg.simulation.process or ():
        if proc.type == "flow" and proc.solvers:
            return proc.solvers[0]
    engine = getattr(getattr(ctx.cfg, "solver", None), "solver_engine", None)
    if engine:
        return str(engine)
    raise ValueError("No flow solver declared in simulation.process or solver.solver_engine")
