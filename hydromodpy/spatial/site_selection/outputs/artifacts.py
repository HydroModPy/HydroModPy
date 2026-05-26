"""Final artifact assembly for site-selection runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult
from hydromodpy.spatial.site_selection.outputs.manifest import (
    SITE_SELECTION_MANIFEST_NAME,
    build_selection_manifest,
    write_selection_manifest,
)
from hydromodpy.spatial.site_selection.reports.figures import MAP_PNG_NAME
from hydromodpy.spatial.site_selection.reports.html import render_site_selection_html_report


def write_manifest_and_optional_report(
    *,
    config: SiteSelectionConfig,
    selection: SelectionResult,
    output_paths: dict[str, Path],
    action: str,
    input_paths: dict[str, str | Path | None] | None = None,
    flow_products: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """Write the official manifest and, when configured, the HTML report."""

    root = config.output_root.expanduser().resolve()
    manifest_path = root / SITE_SELECTION_MANIFEST_NAME
    report_path = root / "review" / "index.html"
    map_path = root / "review" / MAP_PNG_NAME
    manifest_output_paths = {
        **output_paths,
        "site_selection_manifest_json": manifest_path,
    }
    if config.output.write_report_html:
        manifest_output_paths["site_selection_report_html"] = report_path
        manifest_output_paths["site_selection_map_png"] = map_path

    manifest = build_selection_manifest(
        config=config.model_copy(update={"output_root": root}),
        result=selection,
        output_paths=manifest_output_paths,
        action=action,
        input_paths=input_paths,
        flow_products=flow_products,
    )
    write_selection_manifest(manifest_path, manifest)

    paths = {"site_selection_manifest_json": manifest_path}
    if config.output.write_report_html:
        paths["site_selection_report_html"] = render_site_selection_html_report(manifest_path)
        paths["site_selection_map_png"] = map_path
    return paths


__all__ = ["write_manifest_and_optional_report"]
