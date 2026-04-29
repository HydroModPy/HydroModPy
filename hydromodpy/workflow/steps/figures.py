"""Figures step - render display figures declared in [display]."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.results.run import Run
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


def step_render_figures(
    ctx: WorkflowContext,
    run: Run,
    *,
    sim_id: str,
    run_name: str | None,
    headless: bool = False,
    no_display: bool = False,
    figures: list[str] | None = None,
) -> list[Path]:
    """Render the figures declared in [display].figures.

    Returns the list of files produced (possibly empty). Exits early if the
    caller is headless, if display is disabled, or if no figures are declared.
    Rendering errors are logged but do not propagate.
    """
    if headless or no_display:
        return []
    display_cfg = getattr(ctx.cfg, "display", None)
    if display_cfg is None or not display_cfg.enabled:
        return []
    requested = figures or display_cfg.figures
    if not requested:
        return []

    from hydromodpy.display.runs import (
        render_figures_for_run,
        resolve_run_output_dir,
    )

    project_root = ctx.setup.workspace.project_root
    out_dir = resolve_run_output_dir(
        display_cfg,
        project_root=project_root,
        run_name=run_name,
        sim_id=sim_id,
    )
    try:
        return list(render_figures_for_run(run, display_cfg, output_dir=out_dir))
    except Exception:
        logger.exception("Auto-render of figures failed for sim %s", sim_id)
        return []
