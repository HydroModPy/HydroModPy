"""Store-lifecycle step - open, register, finalize, and close SimulationCatalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.steps.persistence import (
    step_persist_geographic,
    step_persist_mesh,
    step_persist_params,
)
from hydromodpy.workflow.steps.registration import collect_registration_kwargs

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


def _register_tracked_input_files(ctx: WorkflowContext) -> None:
    """Walk the config tree and persist every InputFile-marked path."""
    from hydromodpy.core.tracking import collect_input_files

    try:
        entries = collect_input_files(ctx.cfg)
    except Exception as exc:
        logger.warning("Skipping tracked-file registration: %s", exc)
        return

    portable = [e for e in entries if e.portable]
    if not portable:
        return
    written = ctx.store.register_tracked_files(ctx.sim_id, portable)
    logger.info(
        "Registered %d tracked input file(s) for simulation %s",
        written,
        ctx.sim_id,
    )


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
    ctx.store = SimulationCatalog(workspace.root)
    ctx.sim_id = str(uuid4())

    project_name = workspace.project_root.name
    plan = ctx.execution.simulation_plan

    reg_kwargs = collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id
    on_collision = getattr(ctx.cfg.simulation, "on_collision", "replace")
    registration = ctx.store.register_simulation(
        ctx.sim_id,
        project=project_name,
        solver=",".join(r.solver for r in plan.runs),
        name=ctx.setup.run_id,
        on_collision=on_collision,
        **reg_kwargs,
    )
    if registration.name and registration.name != ctx.setup.run_id:
        ctx.setup.run_id = registration.name
    # ``step_open_store`` only needs the simulation row / on-disk store to
    # exist; keep no extra bootstrap handle open across subsequent writes.
    if registration.zarr is not None:
        registration.zarr.close()

    # Capture host environment for ML reproducibility filtering.
    try:
        project_root = getattr(workspace, "project_root", None)
        ctx.store.write_run_environment(ctx.sim_id, project_root=project_root)
    except Exception:
        logger.exception("Failed to capture run environment for sim %s", ctx.sim_id[:8])

    _register_tracked_input_files(ctx)

    if ctx.setup.flow is not None:
        step_persist_params(
            ctx.store,
            ctx.sim_id,
            ctx.setup.flow,
            domain=ctx.cfg.domain,
        )

    step_persist_mesh(ctx, ctx.sim_id)
    step_persist_geographic(ctx, ctx.sim_id)


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
