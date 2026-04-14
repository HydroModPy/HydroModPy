"""Store-lifecycle step — open, register, finalize, and close SimulationCatalog."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def _collect_registration_kwargs(ctx: WorkflowContext) -> dict:
    """Gather all available metadata from ctx for register_simulation()."""
    kwargs: dict = {}

    # Flow regime
    kwargs["flow_regime"] = ctx.cfg.flow.flow_regime

    # Config snapshot
    try:
        config_dict = ctx.cfg.model_dump(mode="json")
        kwargs["config"] = config_dict
    except Exception:
        pass

    # Mesh metadata
    mesh = ctx.setup.mesh_planar
    if mesh is not None:
        kwargs["n_cells"] = mesh.n_cells
        kwargs["mesh_type"] = getattr(mesh, "cell_type", None)
        kwargs["cell_types"] = [getattr(mesh, "cell_type", "unknown")]
        bbox = getattr(mesh, "bounds", None)
        if bbox is not None:
            kwargs["bbox"] = list(bbox)
        # Mesh hash from topology arrays
        try:
            mesh_bytes = mesh.points_xy.tobytes() + mesh.connectivity.tobytes()
            kwargs["mesh_hash"] = hashlib.sha256(mesh_bytes).hexdigest()
        except Exception:
            pass

    # CRS
    crs = getattr(ctx.cfg.geographic, "crs_project", None)
    if crs is not None:
        kwargs["crs"] = str(crs)

    # Time grid
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


def _write_flow_parameters(store, sim_id: str, flow) -> None:
    """Write hydraulic parameters from a Flow object into the catalog."""
    params_dict = getattr(flow, "parameters", None)
    if not params_dict:
        return
    params = []
    for pid, fp in params_dict.items():
        kind = getattr(fp, "kind", "homogeneous")
        if kind == "homogeneous":
            params.append({
                "param_name": pid,
                "zone_id": None,
                "value": getattr(fp, "value", None),
                "unit": getattr(fp, "unit", ""),
                "parameterization": "homogeneous",
            })
        else:
            values_by_key = getattr(fp, "values_by_key", None) or {}
            for zone_key, val in values_by_key.items():
                params.append({
                    "param_name": pid,
                    "zone_id": str(zone_key),
                    "value": val,
                    "unit": getattr(fp, "unit", ""),
                    "parameterization": "geology_mapped",
                })
    if params:
        store.write_parameters(sim_id, params)


def step_open_store(ctx: WorkflowContext) -> None:
    """Open a ``SimulationCatalog`` and register the current simulation.

    Does nothing when ``cfg.simulation.results.store`` is disabled.
    After this step ``ctx.store`` and ``ctx.sim_id`` are set.
    """
    results_cfg = ctx.cfg.simulation.results
    if not results_cfg.store:
        return

    from uuid import uuid4

    from hydromodpy.results.catalog import SimulationCatalog

    workspace = ctx.setup.workspace
    workspace_root = getattr(workspace, "workspace_root", None)
    if workspace_root is None:
        workspace_root = workspace.project_root

    ctx.store = SimulationCatalog(workspace_root)
    ctx.sim_id = str(uuid4())

    project_name = workspace.project_root.name
    plan = ctx.execution.simulation_plan

    reg_kwargs = _collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id
    ctx.store.register_simulation(
        ctx.sim_id,
        project=project_name,
        solver=",".join(r.solver for r in plan.runs),
        name=ctx.setup.run_id,
        run_id=ctx.setup.run_id,
        **reg_kwargs,
    )

    # Write hydraulic parameters
    if ctx.setup.flow is not None:
        _write_flow_parameters(ctx.store, ctx.sim_id, ctx.setup.flow)

    # Write mesh topology into Zarr
    mesh = ctx.setup.mesh_planar
    if mesh is not None:
        domain = ctx.setup.domain
        z_intf = None
        if domain is not None:
            z_intf_attr = getattr(domain, "z_interfaces", None)
            if z_intf_attr is not None:
                import numpy as np
                z_intf = np.asarray(z_intf_attr)
        if z_intf is None:
            import numpy as np
            z_intf = np.array([0.0, -10.0])
        ctx.store.write_mesh(
            ctx.sim_id,
            vertices=mesh.points_xy,
            face_node_connectivity=mesh.connectivity,
            z_interfaces=z_intf,
        )

    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is not None:
        persist_geographic_to_store(
            ctx.setup.geographic, ctx.store,
            sim_id=ctx.sim_id,
        )


def step_finalize_store(
    ctx: WorkflowContext,
    *,
    wall_seconds: float = 0.0,
) -> None:
    """Finalize the simulation in the store and close it.

    After this step ``ctx.store`` is ``None``.
    """
    if ctx.store is None:
        return

    try:
        ctx.store.finalize(
            ctx.sim_id,
            status="completed",
            duration_s=wall_seconds,
        )
    finally:
        ctx.store.close()
        ctx.store = None
