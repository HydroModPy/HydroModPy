"""Static HTML report for site-selection outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hydromodpy.display.report_blocks import (
    write_report_page,
    write_report_page_with_block_variants,
)
from hydromodpy.reporting.site_selection.blocks import (
    DETAIL_LEVELS,
    blocks_for_detail_level,
    build_site_selection_result_block_variants,
    build_site_selection_result_blocks,
)
from hydromodpy.reporting.site_selection.figures import render_site_selection_map
from hydromodpy.schema.site_selection_manifest import (
    load_selection_manifest,
    manifest_output_path,
    validate_selection_manifest,
)

REPORT_DIR_NAME = "review"
REPORT_HTML_NAME = "index.html"


def render_site_selection_html_report(
    manifest_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Render a compact static HTML review page from a selection manifest."""

    manifest_file = Path(manifest_path).expanduser().resolve()
    validation_errors = validate_selection_manifest(
        manifest_file,
        skip_output_keys=(
            "site_selection_report_html",
            "site_selection_map_png",
            "report_artifact_manifest_json",
        ),
    )
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    manifest = load_selection_manifest(manifest_file)
    output_root = Path(str(manifest.get("output_root") or manifest_file.parent)).resolve()
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_root / REPORT_DIR_NAME / REPORT_HTML_NAME
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    selected = _read_csv(
        manifest_output_path(manifest, "selected_sites_csv", manifest_path=manifest_file)
    )
    rejected = _read_csv(
        manifest_output_path(manifest, "rejected_sites_csv", manifest_path=manifest_file)
    )
    decisions = _read_jsonl(
        manifest_output_path(
            manifest, "site_selection_decisions_jsonl", manifest_path=manifest_file
        )
    )
    components = _read_jsonl(
        manifest_output_path(manifest, "criteria_components_jsonl", manifest_path=manifest_file)
    )
    evidence = _read_jsonl(
        manifest_output_path(manifest, "observation_evidence_jsonl", manifest_path=manifest_file)
    )
    candidate_generation = _read_jsonl(
        manifest_output_path(manifest, "candidate_generation_jsonl", manifest_path=manifest_file)
    )
    map_path = render_site_selection_map(manifest_file)
    selection_id = str(manifest.get("selection_id", "site_selection"))

    blocks = build_site_selection_result_blocks(
        manifest,
        manifest_path=manifest_file,
        output_root=output_root,
        map_path=map_path,
        selected=selected,
        rejected=rejected,
        decisions=decisions,
        components=components,
        evidence=evidence,
        candidate_generation=candidate_generation,
    )
    variants = build_site_selection_result_block_variants(
        manifest,
        manifest_path=manifest_file,
        output_root=output_root,
        map_path=map_path,
        selected=selected,
        rejected=rejected,
        decisions=decisions,
        components=components,
        evidence=evidence,
        candidate_generation=candidate_generation,
    )
    subtitle = (
        f"Rapport HTML v0 - selection de sites HydroModPy. {manifest.get('created_at_utc', '')}"
    )
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


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = [
    "REPORT_DIR_NAME",
    "REPORT_HTML_NAME",
    "render_site_selection_html_report",
]
