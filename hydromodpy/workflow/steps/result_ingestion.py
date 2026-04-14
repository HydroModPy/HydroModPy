"""Result-ingestion step — ingest solver outputs and save run artifacts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import ProcessRun, RunExecutionResult
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def step_ingest_run_results(
    ctx: WorkflowContext,
    run: ProcessRun,
    result: RunExecutionResult,
) -> None:
    """Ingest solver outputs into ``ctx.store`` after one run completes."""
    if ctx.store is None:
        return

    from hydromodpy.simulation.results.post_run import post_run_results

    results_cfg = ctx.cfg.simulation.results
    post_run_results(
        sim_id=ctx.sim_id,
        solver_name=run.solver,
        solver_output_dir=result.solver_output_dir,
        results_config=results_cfg,
        store=ctx.store,
        keep_solver_files=True,
        run_id=ctx.setup.run_id,
    )


def step_save_run_artifacts(
    ctx: WorkflowContext,
    wall_seconds: float,
) -> None:
    """Save config snapshot and optional capability gallery."""
    project_root = ctx.setup.workspace.project_root

    # Config snapshot
    snapshot_path = project_root / "_config_snapshot.toml"
    try:
        import tomli_w

        snapshot_path.write_bytes(tomli_w.dumps(ctx.raw_toml).encode())
    except Exception:
        pass

    # Capability gallery
    gallery_cfg = getattr(ctx.cfg, "capability_gallery", None)
    if gallery_cfg is not None and getattr(gallery_cfg, "enabled", False):
        from hydromodpy.analysis.capability_gallery import (
            publish_run_to_capability_gallery,
        )

        plan = ctx.execution.simulation_plan
        solvers_used = {r.solver for r in plan.runs} if plan is not None else set()
        publish_run_to_capability_gallery(
            run_id=str(ctx.setup.run_id),
            run_folder=project_root,
            config=gallery_cfg,
            solvers=tuple(str(s) for s in solvers_used),
        )
