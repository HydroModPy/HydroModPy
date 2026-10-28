"""Run a site selection declared in a TOML file.

``hmp site select <file>`` calls :func:`run_site_selection`. The file holds a
``[site_selection]`` section, plus ``[hydrometry]`` for an observation-led
selection and ``[data.dem]`` to name the DEM. Every output goes under the
``output_root`` the file declares. The HTML report is drawn by the reporting
layer: the caller passes its renderers, this module never imports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigMissingError,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.spatial.site_selection.config.site_selection_config import (
    SiteSelectionConfig,
)
from hydromodpy.workflow.site_selection.build_from_toml import (
    build_dem_area_light_site_selection_from_toml,
    build_generated_site_selection_from_toml,
    build_observed_site_selection_from_toml,
    log_progress,
)
from hydromodpy.workflow.site_selection.catchments_csv import (
    select_delineated_catchments_from_csv,
)
from hydromodpy.workflow.site_selection.data_loading import (
    load_site_selection_config,
)
from hydromodpy.workflow.site_selection.selection_plan import (
    ProgressCallback,
    ReportRenderer,
    plan_site_selection,
)


@dataclass(frozen=True)
class SelectionRun:
    """What one selection did: its action, its counts and the files it wrote."""

    action: str
    selection_id: str
    output_root: Path
    counts: dict[str, int]
    outputs: dict[str, Path]


def run_site_selection(
    config_path: str | Path,
    *,
    report_renderer: ReportRenderer | None = None,
    plan_report_renderer: ReportRenderer | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SelectionRun:
    """Run the selection a TOML file declares and return what it wrote.

    ``[site_selection.input] mode`` picks the action; ``plan_only`` validates
    the file and writes its plan manifest. :func:`plan_site_selection` alone
    validates without writing anything. The renderers
    draw the HTML report when ``[site_selection.output] write_report_html`` is
    true; without them no report is written.
    """

    path = Path(config_path).expanduser().resolve()
    raw = load_toml_with_base_config(path)
    _refuse_a_workflow_mode(raw)
    cfg = load_site_selection_config(path)
    action = _resolve_action(cfg, raw)
    progress = progress_callback or log_progress

    if action == "plan":
        return _run_plan(path, cfg, plan_report_renderer=plan_report_renderer)

    if action == "delineated_catchments":
        if cfg.input.catchments_csv is None:
            raise ConfigMissingError("site_selection.input.catchments_csv is required.")
        result, paths = select_delineated_catchments_from_csv(
            config_path=path,
            catchments_csv=cfg.input.catchments_csv,
            region_id=cfg.input.region_id,
            report_renderer=report_renderer,
        )
        return SelectionRun(
            action=action,
            selection_id=cfg.selection_id,
            output_root=cfg.output_root,
            counts={"selected": len(result.selected), "rejected": len(result.rejected)},
            outputs=dict(paths),
        )

    if action == "generated_candidates":
        if cfg.outlets.candidate_mode != "network_sampling":
            raise ConfigError(
                "site_selection.input.mode='generated_candidates' requires "
                "site_selection.outlets.candidate_mode='network_sampling'."
            )
        build = build_generated_site_selection_from_toml
    elif action == "dem_area_light":
        build = build_dem_area_light_site_selection_from_toml
    else:
        if cfg.strategy.principle != "observation_led":
            raise ConfigError(
                "site_selection input mode 'hydrometry' currently requires "
                "strategy.principle='observation_led'."
            )
        build = build_observed_site_selection_from_toml
    built = build(
        config_path=path,
        workspace_root=cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        progress_callback=progress,
        report_renderer=report_renderer,
    )
    return SelectionRun(
        action=action,
        selection_id=cfg.selection_id,
        output_root=cfg.output_root,
        counts={
            "candidates": len(built.candidates),
            "selected": len(built.selection.selected),
            "rejected": len(built.selection.rejected),
        },
        outputs=dict(built.output_paths),
    )


def _run_plan(
    path: Path,
    cfg: SiteSelectionConfig,
    *,
    plan_report_renderer: ReportRenderer | None,
) -> SelectionRun:
    """Validate the file, then write the plan manifest and its report."""

    plan = plan_site_selection(path)
    outputs: dict[str, Path] = {}
    wants_report = cfg.output.write_report_html and plan_report_renderer is not None
    if cfg.input.write_plan_manifest or wants_report:
        outputs["plan_manifest"] = plan.write_manifest()
    if wants_report:
        outputs["site_selection_report_html"] = plan_report_renderer(outputs["plan_manifest"])
    return SelectionRun(
        action="plan",
        selection_id=cfg.selection_id,
        output_root=cfg.output_root,
        counts={},
        outputs=outputs,
    )


def _refuse_a_workflow_mode(raw: dict[str, Any]) -> None:
    """Refuse a selection file that still declares a workflow mode."""

    workflow = raw.get("workflow")
    if isinstance(workflow, dict) and "mode" in workflow:
        raise ConfigError(
            "[workflow] mode is not read by a site selection: hmp site select <file> "
            "runs it. Remove [workflow] mode from the file."
        )


def _resolve_action(cfg: SiteSelectionConfig, raw: dict[str, Any]) -> str:
    mode = cfg.input.mode

    if mode == "plan_only":
        return "plan"
    if mode in {"delineated_catchments", "generated_candidates", "dem_area_light"}:
        return mode
    if mode == "hydrometry":
        if not isinstance(raw.get("hydrometry"), dict):
            raise ConfigMissingError(
                "site_selection.input.mode='hydrometry' requires [hydrometry]."
            )
        return "hydrometry"

    raise ConfigError(f"Unsupported site_selection.input.mode={mode!r}.")


__all__ = [
    "SelectionRun",
    "run_site_selection",
]
