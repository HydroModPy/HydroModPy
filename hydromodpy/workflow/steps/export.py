"""Export step - save run artifacts, finalize the store, clean scratch."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError, ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import DerivedState, ExportedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Run artifact persistence
# ---------------------------------------------------------------------------


def step_save_run_artifacts(
    ctx: WorkflowContext,
    wall_seconds: float,
) -> None:
    """Save optional run artifacts."""
    analysis_cfg = getattr(ctx.cfg, "analysis", None)
    gallery_cfg = (
        getattr(analysis_cfg, "capability_gallery", None) if analysis_cfg is not None else None
    )
    if gallery_cfg is not None and getattr(gallery_cfg, "enabled", False):
        project_root = ctx.setup.workspace.project_root
        from hydromodpy.analysis.capability_gallery import (
            publish_run_to_capability_gallery,
        )
        from hydromodpy.display.runs import render_figure

        plan = ctx.execution.simulation_plan
        solvers_used = {r.solver for r in plan.runs} if plan is not None else set()

        run_wrapper = None
        if ctx.store is not None and ctx.sim_id is not None:
            try:
                from hydromodpy.results.run import Run as _Run

                run_wrapper = _Run(ctx.sim_id, ctx.store)
            except Exception as exc:
                logger.warning(
                    "Could not build Run wrapper for capability gallery: %s",
                    exc,
                    exc_info=True,
                )
                run_wrapper = None

        def _render(figure_name: str, run: object, target_path: Path) -> None:
            render_figure(figure_name, run, save=target_path)

        publish_run_to_capability_gallery(
            run_id=str(ctx.setup.run_id),
            run_folder=project_root,
            config=gallery_cfg,
            solvers=tuple(str(s) for s in solvers_used),
            run=run_wrapper,
            render_figure=_render,
        )


# ---------------------------------------------------------------------------
# Store finalization
# ---------------------------------------------------------------------------


def step_finalize_store(
    ctx: WorkflowContext,
    *,
    wall_seconds: float = 0.0,
    status: str = "completed",
) -> None:
    """Finalize the simulation in the store and close it.

    After this step ``ctx.store`` is ``None``.
    """
    if ctx.store is None:
        return

    try:
        ctx.store.finalize(
            ctx.sim_id,
            status=status,
            duration_s=wall_seconds,
        )
    finally:
        ctx.store.close()
        ctx.store = None


# ---------------------------------------------------------------------------
# Scratch cleanup
# ---------------------------------------------------------------------------


def step_cleanup_scratch(
    ctx: WorkflowContext,
    *,
    keep_solver_files: bool = False,
) -> None:
    """Remove .solver_scratch/ unless keep_solver_files is True."""
    if keep_solver_files:
        return
    workspace = ctx.setup.workspace
    if workspace is None:
        return
    scratch = workspace.solver_scratch_folder
    if scratch.exists():
        try:
            shutil.rmtree(scratch)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ExportError(f"Could not remove solver scratch directory: {scratch}") from exc


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class ExportStep:
    """Save artefacts, finalize and close the catalog."""

    name = "export"
    tin: ClassVar[type] = DerivedState
    tout: ClassVar[type] = ExportedState
    config_sections: ClassVar[tuple[str, ...]] = ()

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExportStep requires 'ctx' in state.data")

        wall_seconds = float(state.get("wall_seconds", 0.0) or 0.0)

        results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results
        if ctx.store is not None:
            step_save_run_artifacts(ctx, wall_seconds)
            plan = ctx.execution.simulation_plan
            if plan is not None and not ctx.execution.lightweight and ctx.sim_id is not None:
                from hydromodpy.simulation.extraction.post_run import (
                    auto_export_results,
                    cleanup_solver_outputs,
                )
                from hydromodpy.simulation.planning.plan import RunContext

                auto_export_results(
                    sim_id=ctx.sim_id,
                    store=ctx.store,
                    results_config=results_cfg,
                    run_id=ctx.setup.run_id,
                )
                for run in plan.runs:
                    cleanup_solver_outputs(
                        ctx=RunContext(plan=plan, run=run, state=ctx),
                        results_config=results_cfg,
                        keep_solver_files=bool(getattr(results_cfg, "keep_solver_files", False)),
                    )
            step_finalize_store(ctx, wall_seconds=wall_seconds)
        step_cleanup_scratch(
            ctx,
            keep_solver_files=bool(getattr(results_cfg, "keep_solver_files", False)),
        )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
