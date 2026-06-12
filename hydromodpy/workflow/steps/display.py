"""Step 11 - auto-render the figures listed in ``[display].figures``.

Runs after :class:`ExportStep`. Reopens the catalog in read-only fashion
(``ExportStep`` closes it), loads the freshly persisted :class:`Run`, and
renders each figure declared in the TOML into
``<project_root>/<display.output_dir>/<run_name>/``.

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
from hydromodpy.workflow.internals.state import ExportedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.run import Run
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


def _render_figures_tracked(
    run: Run,
    display_cfg: DisplayConfig,
    *,
    output_dir: Path,
    figure_names: list[str],
) -> list[Path]:
    """Render figures one at a time so the progress bar advances per figure."""
    from hydromodpy.display.runs import render_figures_for_run

    written: list[Path] = []
    for figure_name in progress.track(figure_names, "Rendering figures"):
        written.extend(
            render_figures_for_run(
                run,
                display_cfg,
                output_dir=output_dir,
                figure_names=[figure_name],
            )
        )
    return written


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
    """Render the figures declared in ``[display].figures`` at pipeline end."""

    name = "display"
    tin: ClassVar[type] = ExportedState
    tout: ClassVar[type] = ExportedState
    config_sections: ClassVar[tuple[str, ...]] = ("display",)

    def depends_on(self) -> tuple[str, ...]:
        return ("export",)

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
        from hydromodpy.results.catalog import Catalog

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("DisplayStep requires 'ctx' in state.data")

        rendered: list = []

        if state.get("skip_display"):
            logger.info("DisplayStep skipped (skip_display=True)")
        else:
            display_cfg = getattr(ctx.cfg, "display", None)
            sim_id = getattr(ctx, "sim_id", None)
            if display_cfg is None or sim_id is None:
                logger.debug("DisplayStep: no display config or sim_id, skipping")
            elif not display_cfg.enabled or not display_cfg.figures:
                logger.debug(
                    "DisplayStep: nothing to render (enabled=%s, figures=%s)",
                    display_cfg.enabled,
                    list(display_cfg.figures),
                )
            else:
                workspace = ctx.setup.workspace
                project_root = workspace.project_root
                with Catalog.from_workspace(workspace) as catalog:
                    sim = catalog[sim_id]
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
