"""Static HTML report for site-selection planning manifests."""

from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.display.report_blocks import (
    write_report_page,
    write_report_page_with_block_variants,
)
from hydromodpy.reporting.site_selection.blocks import (
    DETAIL_LEVELS,
    blocks_for_detail_level,
    build_site_selection_plan_block_variants,
    build_site_selection_plan_blocks,
)

PLAN_REPORT_DIR_NAME = "review"
PLAN_REPORT_HTML_NAME = "index.html"


def render_site_selection_plan_html_report(
    plan_manifest_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Render a static HTML review page from a plan-only manifest."""

    manifest_file = Path(plan_manifest_path).expanduser().resolve()
    plan = json.loads(manifest_file.read_text(encoding="utf-8"))
    output_root = _resolve_output_root(plan, manifest_file=manifest_file)
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_root / PLAN_REPORT_DIR_NAME / PLAN_REPORT_HTML_NAME
    )
    selection_id = str(plan.get("selection_id") or "site_selection_plan")
    blocks = build_site_selection_plan_blocks(
        plan,
        manifest_path=manifest_file,
        output_root=output_root,
    )
    variants = build_site_selection_plan_block_variants(
        plan,
        manifest_path=manifest_file,
        output_root=output_root,
    )
    subtitle = "Rapport HTML de plan - site selection HydroModPy."
    level_links = _level_links(destination)
    for level in DETAIL_LEVELS:
        write_report_page(
            output_path=level_links[level],
            title=selection_id,
            subtitle=subtitle,
            blocks=blocks_for_detail_level(blocks, level),
            current_level=level,
            level_links=level_links,
        )
    return write_report_page_with_block_variants(
        output_path=destination,
        title=selection_id,
        subtitle=subtitle,
        block_variants=variants,
        current_level="by_block",
        default_level="standard",
        level_links=level_links,
    )


def _level_links(destination: Path) -> dict[str, Path]:
    return {
        "compact": destination.parent / "compact" / destination.name,
        "standard": destination.parent / "standard" / destination.name,
        "audit": destination.parent / "audit" / destination.name,
        "by_block": destination,
    }


def _resolve_output_root(plan: dict, *, manifest_file: Path) -> Path:
    output_root = Path(str(plan.get("output_root") or manifest_file.parent)).expanduser()
    if not output_root.is_absolute():
        return (manifest_file.parent / output_root).resolve()
    return output_root.resolve()


__all__ = [
    "PLAN_REPORT_DIR_NAME",
    "PLAN_REPORT_HTML_NAME",
    "render_site_selection_plan_html_report",
]
