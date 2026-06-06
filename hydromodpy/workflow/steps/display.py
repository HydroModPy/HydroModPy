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

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.display.report_profiles import (
    effective_display_config_for_report,
    merge_display_figures,
    report_html_is_enabled,
    report_html_is_strict,
    report_profile_name,
    required_display_figures_for_report,
    write_display_report_artifact_manifest,
)
from hydromodpy.workflow.internals.state import ExportedState, PipelineState

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
    report_cfg = getattr(ctx.cfg, "report", None)
    if display_cfg is None:
        return []
    if not display_cfg.enabled and not report_html_is_enabled(report_cfg):
        return []
    requested = merge_display_figures(figures or display_cfg.figures, report_cfg)
    if not requested:
        return []

    from hydromodpy.display.runs import (
        render_figures_for_run,
        resolve_run_output_dir,
    )

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
    effective_display_cfg = effective_display_config_for_report(
        display_cfg,
        report_cfg,
        figures=requested,
    )
    try:
        return list(
            render_figures_for_run(
                run,
                effective_display_cfg,
                output_dir=out_dir,
                figure_names=requested,
            )
        )
    except Exception:
        logger.exception("Auto-render of figures failed for sim %s", sim_id)
        return []


class DisplayStep:
    """Render the figures declared in ``[display].figures`` at pipeline end."""

    name = "display"
    tin: ClassVar[type] = ExportedState
    tout: ClassVar[type] = ExportedState
    config_sections: ClassVar[tuple[str, ...]] = ("display", "report")

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
        report_manifest: Path | None = None
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
                    candidate_manifest = Path(out_dir) / "report_artifact_manifest.json"
                    if candidate_manifest.exists():
                        report_manifest = candidate_manifest
            except Exception:
                rendered = []
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
            report_display_manifest=report_manifest,
        )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.display.runs import (
            render_figures_for_run,
            resolve_run_output_dir,
        )
        from hydromodpy.results.catalog import SimulationCatalog

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("DisplayStep requires 'ctx' in state.data")

        rendered: list = []
        report_manifest = None

        if state.get("skip_display"):
            logger.info("DisplayStep skipped (skip_display=True)")
        else:
            display_cfg = getattr(ctx.cfg, "display", None)
            report_cfg = getattr(ctx.cfg, "report", None)
            sim_id = getattr(ctx, "sim_id", None)
            if display_cfg is None or sim_id is None:
                logger.debug("DisplayStep: no display config or sim_id, skipping")
            elif not display_cfg.enabled and not report_html_is_enabled(report_cfg):
                logger.debug("DisplayStep: display disabled and no report artifacts requested")
            else:
                requested = merge_display_figures(display_cfg.figures, report_cfg)
                if not requested:
                    logger.debug(
                        "DisplayStep: nothing to render (enabled=%s, figures=%s)",
                        display_cfg.enabled,
                        list(display_cfg.figures),
                    )
                    return state.advance(
                        step_index=state.step_index + 1,
                        step_name=self.name,
                        ctx=ctx,
                        rendered_figures=rendered,
                        report_display_manifest=report_manifest,
                    )
                workspace = ctx.setup.workspace
                project_root = workspace.project_root
                effective_display_cfg = effective_display_config_for_report(
                    display_cfg,
                    report_cfg,
                    figures=requested,
                )
                with SimulationCatalog.from_workspace(workspace) as catalog:
                    sim = catalog[sim_id]
                    out_dir = resolve_run_output_dir(
                        effective_display_cfg,
                        project_root=project_root,
                        run_name=sim.name,
                        sim_id=sim_id,
                    )
                    rendered = render_figures_for_run(
                        sim,
                        effective_display_cfg,
                        output_dir=out_dir,
                        figure_names=requested,
                    )
                    if report_html_is_enabled(report_cfg):
                        report_required_figures = required_display_figures_for_report(report_cfg)
                        report_manifest = write_display_report_artifact_manifest(
                            out_dir,
                            profile=report_profile_name(report_cfg),
                            requested_figures=report_required_figures,
                            rendered_figures=rendered,
                            base_dir=project_root,
                        )
                        if report_html_is_strict(report_cfg):
                            missing = _missing_required_artifacts(report_manifest)
                            if missing:
                                details = ", ".join(missing)
                                raise ConfigError(
                                    "Report display artifact postflight failed. "
                                    f"Missing required artifacts: {details}"
                                )
                    if rendered:
                        logger.info(
                            "DisplayStep rendered %d figure(s) in %s",
                            len(rendered),
                            out_dir,
                        )
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
            report_display_manifest=report_manifest,
        )


def _missing_required_artifacts(manifest_path: Path) -> tuple[str, ...]:
    import json

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = []
    for artifact in payload.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("required") and artifact.get("status") != "present":
            missing.append(str(artifact.get("artifact_id", "")))
    return tuple(item for item in missing if item)
