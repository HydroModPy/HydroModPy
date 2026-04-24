"""Registration step - insert a simulation row in the catalog and persist inputs."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def collect_registration_kwargs(ctx: WorkflowContext) -> dict:
    """Gather all available metadata from ctx for register_simulation()."""
    kwargs: dict = {"flow_regime": ctx.cfg.flow.flow_regime}

    if getattr(ctx, "config_path", None) is not None:
        kwargs["config_source"] = str(ctx.config_path)

    try:
        kwargs["config"] = ctx.cfg.model_dump(mode="json")
    except Exception:
        pass

    mesh = ctx.setup.mesh_planar
    if mesh is not None:
        kwargs["n_cells"] = mesh.n_cells
        kwargs["mesh_type"] = getattr(mesh, "cell_type", None)
        kwargs["cell_types"] = [getattr(mesh, "cell_type", "unknown")]
        bbox = getattr(mesh, "bounds", None)
        if bbox is not None:
            kwargs["bbox"] = list(bbox)
        try:
            mesh_bytes = mesh.points_xy.tobytes() + mesh.connectivity.tobytes()
            kwargs["mesh_hash"] = hashlib.sha256(mesh_bytes).hexdigest()
        except Exception:
            pass

    crs = getattr(ctx.cfg.geographic, "crs_project", None)
    if crs is not None:
        kwargs["crs"] = str(crs)

    tg = ctx.setup.time_grid
    if tg is not None:
        boundaries = getattr(tg, "boundaries", None)
        if boundaries and len(boundaries) >= 2:
            kwargs["period_start"] = str(boundaries[0])
            kwargs["period_end"] = str(boundaries[-1])
            kwargs["n_timesteps"] = len(boundaries) - 1
        time_cfg = getattr(ctx.cfg.simulation, "time", None)
        if time_cfg is not None:
            kwargs["time_unit"] = getattr(time_cfg, "step_unit", None)

    return kwargs


def step_register_simulation(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    plan: SimulationPlan,
    project_name: str,
    name: str,
) -> str:
    """Register the simulation in the catalog and return the final run name.

    The catalog may rename a run on collision. The returned value is the name
    recorded on disk; callers should use it from here on.
    """
    reg_kwargs = collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id

    solvers = ",".join(r.solver for r in plan.runs)
    registration = ctx.store.register_simulation(
        sim_id,
        project=project_name,
        solver=solvers,
        name=name,
        on_collision=ctx.cfg.simulation.on_collision,
        **reg_kwargs,
    )
    final_name = registration.name or name
    replaced = registration.replaced_sim_id
    short = sim_id[:8]
    if replaced:
        logger.info("Run '%s' stored [%s] (replaced %s)", final_name, short, replaced[:8])
    else:
        logger.info("Run '%s' stored [%s]", final_name, short)
    return final_name
