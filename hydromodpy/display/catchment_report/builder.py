"""Generic catchment report assembly."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.display.catchment_report.artifacts import (
    ReportArtifactSpec,
    artifact_paths,
    copy_real_figures_with_provenance,
    geology_legend_rows,
    write_manifest,
)
from hydromodpy.display.catchment_report.block_specs import ReportBlockSpec
from hydromodpy.display.catchment_report.blocks import (
    PAGE_MODES,
    REPORT_LEVELS,
    assert_monotonic_blocks,
    block_variants_by_id,
    build_blocks,
)
from hydromodpy.display.catchment_report.contract import write_catchment_artifact_manifest
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.presets import (
    GENERIC_REPORT_PRESET,
    CatchmentReportPreset,
    preset_from_name,
)
from hydromodpy.display.report_blocks import (
    write_report_page,
    write_report_page_with_block_variants,
)


@dataclass(frozen=True)
class CatchmentReportConfig:
    output_dir: Path
    site_label: str
    station_label: str
    title: str
    context_summary: Path
    context_assets: Path
    overview_figures: Path
    data_overview_figures: Path
    simulation_figures: Path
    geographic_scratch: Path
    generated_network_root: Path
    context_html: Path
    overview_standard_html: Path
    transient_config: Path
    overview_config: Path
    preset: CatchmentReportPreset = field(default=GENERIC_REPORT_PRESET)
    artifact_specs: tuple[ReportArtifactSpec, ...] | None = None
    block_specs: tuple[ReportBlockSpec, ...] | None = None
    upstream_artifact_manifest: Path | None = None
    upstream_artifact_manifests: tuple[Path, ...] = ()

    @classmethod
    def from_inputs(
        cls,
        inputs: CatchmentReportInputs,
        *,
        preset: CatchmentReportPreset | None = None,
        artifact_specs: tuple[ReportArtifactSpec, ...] | None = None,
        block_specs: tuple[ReportBlockSpec, ...] | None = None,
        upstream_artifact_manifest: Path | None = None,
        upstream_artifact_manifests: tuple[Path, ...] = (),
    ) -> CatchmentReportConfig:
        effective_preset = (
            preset
            if preset is not None
            else preset_from_name(inputs.preset_name)
            if inputs.preset_name
            else GENERIC_REPORT_PRESET
        )
        return cls(
            output_dir=inputs.output_dir,
            site_label=inputs.site_label,
            station_label=inputs.station_label,
            title=inputs.title,
            context_summary=inputs.context_summary,
            context_assets=inputs.context_assets,
            overview_figures=inputs.overview_figures,
            data_overview_figures=inputs.data_overview_figures,
            simulation_figures=inputs.simulation_figures,
            geographic_scratch=inputs.geographic_scratch,
            generated_network_root=inputs.generated_network_root,
            context_html=inputs.context_html,
            overview_standard_html=inputs.overview_standard_html,
            transient_config=inputs.transient_config,
            overview_config=inputs.overview_config,
            preset=effective_preset,
            artifact_specs=artifact_specs,
            block_specs=block_specs,
            upstream_artifact_manifest=upstream_artifact_manifest,
            upstream_artifact_manifests=upstream_artifact_manifests,
        )


def build_catchment_report(config: CatchmentReportConfig) -> Path:
    output_dir = config.output_dir
    title = config.title or f"{config.site_label} - rapport HTML par blocs avec figures reelles"
    web_dir = output_dir / "web"
    figures_dir = web_dir / "figures"
    if figures_dir.exists():
        shutil.rmtree(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)

    summary = _load_json(config.context_summary)
    artifact_specs = _artifact_specs(config)
    block_specs = _block_specs(config)
    copied, figure_provenance = copy_real_figures_with_provenance(
        figures_dir,
        context_assets=config.context_assets,
        overview_figures=config.overview_figures,
        data_overview_figures=config.data_overview_figures,
        simulation_figures=config.simulation_figures,
        artifact_specs=artifact_specs,
        source_artifact_manifest=config.upstream_artifact_manifest,
        source_artifact_manifests=config.upstream_artifact_manifests,
    )
    manifest = write_manifest(
        output_dir,
        copied,
        site_label=config.site_label,
        expected_figure_ids=(spec.figure_id for spec in artifact_specs),
        context_summary=config.context_summary,
        context_assets=config.context_assets,
        overview_figures=config.overview_figures,
        data_overview_figures=config.data_overview_figures,
        simulation_figures=config.simulation_figures,
        geographic_scratch=config.geographic_scratch,
        generated_network_root=config.generated_network_root,
        figure_provenance=figure_provenance,
    )
    write_catchment_artifact_manifest(
        output_dir,
        copied_figures=copied,
        figure_provenance=figure_provenance,
        artifact_specs=artifact_specs,
        block_specs=block_specs,
        context_summary=config.context_summary,
        source_manifest=manifest,
        upstream_artifact_manifest=config.upstream_artifact_manifest,
        upstream_artifact_manifests=config.upstream_artifact_manifests,
        site_label=config.site_label,
    )
    report_artifact_paths = artifact_paths(
        context_html=config.context_html,
        context_summary=config.context_summary,
        overview_standard_html=config.overview_standard_html,
        transient_config=config.transient_config,
        overview_config=config.overview_config,
    )
    geology_rows = geology_legend_rows(config.geographic_scratch)
    level_links = {level: output_dir / "web_review" / level / "index.html" for level in PAGE_MODES}
    blocks_by_level = {
        level: build_blocks(
            summary=summary,
            copied=copied,
            manifest=manifest,
            detail_level=level,
            site_label=config.site_label,
            station_label=config.station_label,
            geology_rows=geology_rows,
            artifact_paths=report_artifact_paths,
            block_specs=block_specs,
        )
        for level in REPORT_LEVELS
    }
    assert_monotonic_blocks(blocks_by_level)
    block_variants = block_variants_by_id(blocks_by_level)

    html_path = write_report_page(
        output_path=web_dir / "index.html",
        title=title,
        subtitle=_subtitle("standard", site_label=config.site_label),
        blocks=blocks_by_level["standard"],
        current_level="standard",
        level_links=level_links,
    )
    for level in REPORT_LEVELS:
        write_report_page(
            output_path=level_links[level],
            title=title,
            subtitle=_subtitle(level, site_label=config.site_label),
            blocks=blocks_by_level[level],
            current_level=level,
            level_links=level_links,
        )
    write_report_page_with_block_variants(
        output_path=level_links["by_block"],
        title=title,
        subtitle=_subtitle("by_block", site_label=config.site_label),
        block_variants=block_variants,
        current_level="by_block",
        default_level="standard",
        level_links=level_links,
    )
    return html_path


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_specs(config: CatchmentReportConfig) -> tuple[ReportArtifactSpec, ...]:
    if config.artifact_specs is not None:
        return config.artifact_specs
    return config.preset.artifact_specs


def _block_specs(config: CatchmentReportConfig) -> tuple[ReportBlockSpec, ...]:
    if config.block_specs is not None:
        return config.block_specs
    return config.preset.block_specs


def _subtitle(level: str, *, site_label: str) -> str:
    labels = {
        "compact": "vue compacte",
        "standard": "vue standard",
        "audit": "vue audit",
        "by_block": "vue avec niveau choisi bloc par bloc",
    }
    return (
        f"Aggregation des figures {site_label} existantes: contexte bassin, hydrographie, "
        f"forcages, run transitoire de reference et artefacts associes - {labels.get(level, level)}."
    )
