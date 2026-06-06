"""Final artifact assembly for site-selection runs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from hydromodpy.schema.site_selection_manifest import (
    REVIEW_DIR_NAME,
    REVIEW_HTML_NAME,
    REVIEW_MAP_PNG_NAME,
    SITE_SELECTION_MANIFEST_NAME,
    write_selection_manifest,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult
from hydromodpy.spatial.site_selection.outputs.manifest import build_selection_manifest
from hydromodpy.spatial.site_selection.outputs.report_artifacts import (
    REPORT_ARTIFACT_MANIFEST_OUTPUT_KEY,
    write_site_selection_report_artifact_manifest,
)


def write_manifest_and_optional_report(
    *,
    config: SiteSelectionConfig,
    selection: SelectionResult,
    output_paths: dict[str, Path],
    action: str,
    input_paths: dict[str, str | Path | None] | None = None,
    flow_products: dict[str, Any] | None = None,
    report_renderer: Callable[[str | Path], Path] | None = None,
) -> dict[str, Path]:
    """Write the official manifest and, when configured, the HTML report.

    Rendering is delegated to ``report_renderer`` (injected by the workflow
    layer) so this spatial helper never imports the reporting or display stack.
    """

    root = config.output_root.expanduser().resolve()
    manifest_path = root / SITE_SELECTION_MANIFEST_NAME
    report_path = root / REVIEW_DIR_NAME / REVIEW_HTML_NAME
    map_path = root / REVIEW_DIR_NAME / REVIEW_MAP_PNG_NAME
    render = report_renderer if config.output.write_report_html else None
    manifest_output_paths = {
        **output_paths,
        "site_selection_manifest_json": manifest_path,
    }
    if render is not None:
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
    if render is not None:
        paths["site_selection_report_html"] = render(manifest_path)
        paths["site_selection_map_png"] = map_path
    paths[REPORT_ARTIFACT_MANIFEST_OUTPUT_KEY] = write_site_selection_report_artifact_manifest(
        manifest_path
    )
    return paths


__all__ = ["write_manifest_and_optional_report"]
