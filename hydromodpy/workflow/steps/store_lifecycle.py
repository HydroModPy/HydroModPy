"""Store-lifecycle step — open, register, finalize, and close ResultStore.

Code extracted from ``HydroModPyLauncher._open_result_store`` and the
finalization block in ``HydroModPyLauncher.run_prepared``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def step_open_store(ctx: WorkflowContext) -> None:
    """Open a ``ResultStore`` and register the current simulation.

    Does nothing when ``cfg.simulation.results.store`` is disabled.
    After this step ``ctx.store`` and ``ctx.sim_id`` are set.
    """
    results_cfg = ctx.cfg.simulation.results
    if not results_cfg.store:
        return

    from uuid import uuid4

    from hydromodpy.results.store import ResultStore

    workspace = ctx.setup.workspace
    ctx.store = ResultStore(
        project_path=workspace.project_root,
        workspace_path=workspace.workspace_root,
    )
    ctx.sim_id = str(uuid4())

    plan = ctx.execution.simulation_plan
    ctx.store.register_simulation(
        ctx.sim_id,
        name=ctx.setup.run_id,
        solver=",".join(r.solver for r in plan.runs),
        run_id=ctx.setup.run_id,
    )

    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is not None:
        persist_geographic_to_store(ctx.setup.geographic, ctx.store)


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
        plan = ctx.execution.simulation_plan
        process_types = list({r.process_type for r in plan.runs}) if plan else []
        ctx.store.finalize(
            ctx.sim_id,
            status="completed",
            duration_s=wall_seconds,
            process_types=process_types,
        )
    finally:
        ctx.store.close()
        ctx.store = None
