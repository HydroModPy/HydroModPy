"""Export step - save run artifacts, finalize the store, clean scratch."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
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
    """Save config snapshot and optional capability gallery."""
    from hydromodpy.core.toml_io.writer import dumps as dump_toml_text

    project_root = ctx.setup.workspace.project_root

    snapshot_path = project_root / "_config_snapshot.toml"
    try:
        snapshot_path.write_text(dump_toml_text(ctx.raw_toml), encoding="utf-8")
    except Exception:
        pass

    gallery_cfg = getattr(ctx.cfg, "capability_gallery", None)
    if gallery_cfg is not None and getattr(gallery_cfg, "enabled", False):
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
            except Exception:
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
        shutil.rmtree(scratch, ignore_errors=True)


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

        if ctx.store is not None:
            step_save_run_artifacts(ctx, wall_seconds)
            step_finalize_store(ctx, wall_seconds=wall_seconds)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
