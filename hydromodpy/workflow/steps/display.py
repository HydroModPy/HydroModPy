"""Step 11 - auto-render the figures listed in ``[display].figures``.

Runs after :class:`DeriveStep` and before :class:`ExportStep`. Figures are
the last reader of the run: they draw from the still-open store, so they see
the intermediate fields (the raw per-cell budget) that the export step drops
right before sealing. Each figure declared in the TOML is written into
``<project_root>/runs/<run>/<display.output_dir>/``.

Skipped silently when ``display.enabled`` is false, when ``display.figures``
is empty, or when the pipeline was set to headless via
``state.data["skip_display"]`` (honored by the CLI ``--no-display`` flag).

Inputs
------
``ctx`` : WorkflowContext - provides ``sim_id``, ``cfg.display``, workspace.

Outputs
-------
``state`` unchanged aside from the usual ``advance(...)`` bookkeeping. The
rendered file paths are attached via ``state.data["rendered_figures"]`` for
downstream tooling/tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import DerivedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


def _render_figures_tracked(
    run: Run,
    display_cfg: DisplayConfig,
    *,
    output_dir: Path,
    figure_names: list[str],
) -> list[Path]:
    """Render figures one at a time so the progress bar advances per figure.

    Individual figures log nothing on success (a skip or a per-figure failure
    warning aside); this emits a single summary line for the whole batch,
    naming every requested figure that produced nothing.
    """
    from hydromodpy.display.runs import (
        FigureRenderReport,
        log_render_summary,
        render_figures_for_run,
    )

    report = FigureRenderReport()
    for figure_name in progress.track(figure_names, "Rendering figures"):
        report = report.merged_with(
            render_figures_for_run(
                run,
                display_cfg,
                output_dir=output_dir,
                figure_names=[figure_name],
            )
        )
    log_render_summary(report, destination=output_dir)
    return list(report.written)


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

    from hydromodpy.display.runs import resolve_run_output_dir

    workspace = ctx.setup.workspace
    if workspace is None:
        raise ConfigError("Workspace is required to render display figures.")
    project_root = workspace.project_root
    out_dir = resolve_run_output_dir(
        display_cfg,
        project_root=project_root,
        run_name=run_name,
        sim_id=sim_id,
    )
    try:
        return _render_figures_tracked(
            run,
            display_cfg,
            output_dir=out_dir,
            figure_names=list(requested),
        )
    except Exception:
        logger.exception("Auto-render of figures failed for sim %s", sim_id)
        return []


class DisplayStep:
    """Render the figures declared in ``[display].figures`` before export."""

    name = "display"
    tin: ClassVar[type] = DerivedState
    tout: ClassVar[type] = DerivedState
    config_sections: ClassVar[tuple[str, ...]] = ("display",)

    def depends_on(self) -> tuple[str, ...]:
        return ("derive",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """List the previously rendered PNGs from the display output dir."""
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("DisplayStep.rebuild_state requires 'ctx' in state.data")
        rendered: list[Path] = []
        display_cfg = getattr(ctx.cfg, "display", None)
        ws = getattr(getattr(ctx, "setup", None), "workspace", None)
        project_root = getattr(ws, "project_root", None)
        sim_id = getattr(ctx, "sim_id", None)
        if display_cfg is not None and project_root is not None and sim_id is not None:
            try:
                from hydromodpy.display.runs import resolve_run_output_dir

                run_name = getattr(getattr(ctx, "setup", None), "run_id", None)
                out_dir = resolve_run_output_dir(
                    display_cfg,
                    project_root=project_root,
                    run_name=run_name,
                    sim_id=sim_id,
                )
                if Path(out_dir).is_dir():
                    rendered = sorted(Path(out_dir).glob("*.png"))
            except Exception:
                rendered = []
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
        )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.display.runs import resolve_run_output_dir

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("DisplayStep requires 'ctx' in state.data")

        rendered: list = []

        if state.get("skip_display"):
            logger.info("DisplayStep skipped (skip_display=True)")
        else:
            display_cfg = getattr(ctx.cfg, "display", None)
            sim_id = getattr(ctx, "sim_id", None)
            store = getattr(ctx, "store", None)
            if display_cfg is None or sim_id is None or store is None:
                logger.debug("DisplayStep: no display config, sim_id or store, skipping")
            elif not display_cfg.enabled or not display_cfg.figures:
                logger.debug(
                    "DisplayStep: nothing to render (enabled=%s, figures=%s)",
                    display_cfg.enabled,
                    list(display_cfg.figures),
                )
            else:
                project_root = ctx.setup.workspace.project_root
                sim = store[sim_id]
                out_dir = resolve_run_output_dir(
                    display_cfg,
                    project_root=project_root,
                    run_name=sim.name,
                    sim_id=sim_id,
                )
                rendered = _render_figures_tracked(
                    sim,
                    display_cfg,
                    output_dir=out_dir,
                    figure_names=list(display_cfg.figures),
                )
                if rendered:
                    logger.debug(
                        "DisplayStep rendered %d figure(s) in %s",
                        len(rendered),
                        out_dir,
                    )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
        )
