"""Store-lifecycle step — open, register, finalize, and close SimulationCatalog."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


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
    ctx.store.register_simulation(
        ctx.sim_id,
        project=project_name,
        solver=",".join(r.solver for r in plan.runs),
        name=ctx.setup.run_id,
        run_id=ctx.setup.run_id,
    )

    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is not None:
        persist_geographic_to_store(
            ctx.setup.geographic, ctx.store,
            project=project_name, sim_id=ctx.sim_id,
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
