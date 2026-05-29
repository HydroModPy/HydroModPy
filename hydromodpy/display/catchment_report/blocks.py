"""Report block construction for catchment reports."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from hydromodpy.display.catchment_report.block_specs import (
    DEFAULT_BLOCK_SPECS,
    FigureSpec,
    ReportBlockSpec,
)
from hydromodpy.display.report_blocks import (
    DetailLevel,
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportMetric,
    ReportTable,
    key_value_table,
)

REPORT_LEVELS: tuple[DetailLevel, ...] = ("compact", "standard", "audit")
REPORT_LEVEL_RANK = {level: index for index, level in enumerate(REPORT_LEVELS)}
PAGE_MODES = (*REPORT_LEVELS, "by_block")


@dataclass(frozen=True)
class BlockBuildContext:
    summary: dict[str, Any]
    copied: dict[str, Path]
    manifest: Path
    detail_level: DetailLevel
    site_label: str
    station_label: str
    geology_rows: tuple[Mapping[str, Any], ...]
    artifact_paths: dict[str, Path]
    config: dict[str, Any]
    stats: dict[str, Any]
    baseline: dict[str, Any]
    network: dict[str, Any]


@dataclass(frozen=True)
class BlockContent:
    metrics: tuple[ReportMetric, ...] = field(default_factory=tuple)
    tables: tuple[ReportTable, ...] = field(default_factory=tuple)
    links: tuple[ReportLink, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _build_blocks(
    *,
    summary: dict[str, Any],
    copied: dict[str, Path],
    manifest: Path,
    detail_level: DetailLevel,
    site_label: str,
    station_label: str,
    geology_rows: tuple[Mapping[str, Any], ...],
    artifact_paths: dict[str, Path],
    block_specs: Sequence[ReportBlockSpec] = DEFAULT_BLOCK_SPECS,
) -> list[ReportBlock]:
    context = BlockBuildContext(
        summary=summary,
        copied=copied,
        manifest=manifest,
        detail_level=detail_level,
        site_label=site_label,
        station_label=station_label,
        geology_rows=geology_rows,
        artifact_paths=artifact_paths,
        config=_mapping(summary.get("configuration")),
        stats=_mapping(summary.get("stats")),
        baseline=_mapping(summary.get("baseline_run")),
        network=_mapping(summary.get("network")),
    )
    return [
        _block_from_spec(spec, context)
        for spec in block_specs
        if _level_at_least(detail_level, spec.minimum_level)
    ]


def _block_from_spec(spec: ReportBlockSpec, context: BlockBuildContext) -> ReportBlock:
    content = _content_for_spec(spec, context)
    return ReportBlock(
        block_id=spec.block_id,
        title=_template(spec.title, context),
        level=context.detail_level,
        lead=_template(spec.lead, context),
        metrics=content.metrics,
        figures=_figures_from_spec(spec.figures, context),
        tables=content.tables,
        links=content.links,
        warnings=content.warnings,
    )


def _content_for_spec(spec: ReportBlockSpec, context: BlockBuildContext) -> BlockContent:
    try:
        builder = _CONTENT_BUILDERS[spec.content_key]
    except KeyError as exc:
        raise ValueError(f"Unknown report block content key: {spec.content_key!r}") from exc
    return builder(context)


def _figures_from_spec(
    figure_specs: Sequence[FigureSpec],
    context: BlockBuildContext,
) -> tuple[ReportFigure, ...]:
    return _for_level(
        context.detail_level,
        (
            (
                figure_spec.minimum_level,
                _figure(
                    context.copied,
                    figure_spec.figure_id,
                    figure_spec.title,
                    required=figure_spec.required,
                ),
            )
            for figure_spec in figure_specs
        ),
    )


def _template(text: str, context: BlockBuildContext) -> str:
    return text.format(site_label=context.site_label, station_label=context.station_label)


def _site_context_content(context: BlockBuildContext) -> BlockContent:
    config = context.config
    baseline = context.baseline
    metrics = _for_level(
        context.detail_level,
        (
            ("compact", ReportMetric("Site", context.station_label)),
            ("standard", ReportMetric("CRS", config.get("crs", "unknown"))),
            ("standard", ReportMetric("Exutoire X", _fmt(config.get("x_outlet")), "m")),
            ("standard", ReportMetric("Exutoire Y", _fmt(config.get("y_outlet")), "m")),
            ("standard", ReportMetric("Fenetre", _window(config))),
            (
                "standard",
                ReportMetric(
                    "Cellules du run de preparation",
                    baseline.get("n_cells", "unknown"),
                ),
            ),
        ),
    )
    table = key_value_table(
        "configuration",
        "Configuration de reference",
        (
            ("Config base", config.get("base_config", "")),
            ("DEM", config.get("dem", "")),
            ("Epaisseur", config.get("thickness", "")),
            ("Drainage", config.get("drainage", "")),
        ),
    )
    return BlockContent(
        metrics=metrics,
        tables=_for_level(context.detail_level, (("standard", table),)),
    )


def _hydraulic_properties_content(context: BlockBuildContext) -> BlockContent:
    config = context.config
    metrics = _for_level(
        context.detail_level,
        (
            ("compact", ReportMetric("K", _fmt(config.get("K", "unknown")), "m/s")),
            ("compact", ReportMetric("Sᵧ", _fmt(config.get("Sy", "unknown")), "-")),
            ("compact", ReportMetric("Ss", _fmt(config.get("Ss", "unknown")), "1/m")),
        ),
    )
    table = key_value_table(
        "hydraulic_properties",
        "Valeurs de reference",
        (
            ("Conductivité hydraulique K", _unit_value(config.get("K", ""), "m/s")),
            ("Rendement spécifique Sᵧ", _unit_value(config.get("Sy", ""), "-")),
            ("Emmagasinement spécifique Ss", _unit_value(config.get("Ss", ""), "1/m")),
        ),
    )
    return BlockContent(
        metrics=metrics,
        tables=_for_level(context.detail_level, (("standard", table),)),
    )


def _spatial_context_content(context: BlockBuildContext) -> BlockContent:
    geology_table = ReportTable(
        "geology_units",
        "Codes geologiques presents",
        columns=(
            ("code", "Code"),
            ("notation", "Notation"),
            ("description", "Nature / description"),
            ("area_km2", "Surface approx. (km2)"),
        ),
        rows=context.geology_rows,
        empty_message="Aucun code geologique disponible.",
    )
    return BlockContent(
        tables=(
            _for_level(context.detail_level, (("standard", geology_table),))
            if context.geology_rows
            else ()
        ),
    )


def _hydrographic_network_content(context: BlockBuildContext) -> BlockContent:
    network = context.network
    return BlockContent(
        metrics=_for_level(
            context.detail_level,
            (
                (
                    "compact",
                    ReportMetric(
                        "Segments BD Topage",
                        network.get("reference_segments", "unknown"),
                    ),
                ),
                (
                    "standard",
                    ReportMetric(
                        "Seuil extraction DEM",
                        _fmt(context.config.get("network_threshold_area_km2", "0.5")),
                        "km2",
                    ),
                ),
                (
                    "audit",
                    ReportMetric("Dossier figures source", network.get("figure_dir", "unknown")),
                ),
            ),
        ),
    )


def _empty_content(context: BlockBuildContext) -> BlockContent:
    return BlockContent()


def _forcing_flux_content(context: BlockBuildContext) -> BlockContent:
    config = context.config
    stats = context.stats
    observed = _mapping(stats.get("observed_discharge"))
    simulated = _mapping(stats.get("baseline_simulated_discharge"))
    rows = _stats_rows(
        (
            ("Debit observe", observed, "m3/s"),
            ("Debit simule", simulated, "m3/s"),
        )
    )
    table = ReportTable(
        table_id="flux_stats",
        title="Chroniques et forcages",
        columns=(
            ("label", "Serie"),
            ("rows", "Points"),
            ("start", "Debut"),
            ("end", "Fin"),
            ("mean", "Moyenne"),
            ("minimum", "Min"),
            ("maximum", "Max"),
            ("unit", "Unite"),
        ),
        rows=tuple(rows),
    )
    return BlockContent(
        metrics=_for_level(
            context.detail_level,
            (
                ("compact", ReportMetric("Origine forcages", _forcing_origin_label(config))),
                (
                    "compact",
                    ReportMetric("Debit observe moyen", _fmt(observed.get("mean")), "m3/s"),
                ),
                (
                    "audit",
                    ReportMetric(
                        "Nombre de points debit observe",
                        observed.get("rows", "unknown"),
                    ),
                ),
            ),
        ),
        tables=_for_level(context.detail_level, (("audit", table),)),
    )


def _simulation_outputs_content(context: BlockBuildContext) -> BlockContent:
    baseline = context.baseline
    baseline_q = _mapping(context.stats.get("baseline_simulated_discharge"))
    return BlockContent(
        metrics=_for_level(
            context.detail_level,
            (
                (
                    "audit",
                    ReportMetric("Simulation", baseline.get("simulation_name", "unknown")),
                ),
                ("audit", ReportMetric("Pas temporels", baseline.get("n_timesteps", "unknown"))),
                (
                    "audit",
                    ReportMetric("Temps solveur", _fmt(baseline.get("runtime_seconds")), "s"),
                ),
                (
                    "audit",
                    ReportMetric(
                        "Debit simule moyen du run de reference",
                        _fmt(baseline_q.get("mean")),
                        "m3/s",
                    ),
                ),
            ),
        ),
    )


def _artifacts_content(context: BlockBuildContext) -> BlockContent:
    artifact_paths = context.artifact_paths
    links = (
        ReportLink("Manifest du rapport blocs", context.manifest, kind="json"),
        ReportLink(
            f"Contexte {context.site_label} HTML",
            artifact_paths["context_html"],
            kind="html",
        ),
        ReportLink(
            f"Rapport {context.site_label} overview standard",
            artifact_paths["overview_standard_html"],
            kind="html",
        ),
        ReportLink("Resume contexte bassin", artifact_paths["context_summary"], kind="json"),
        ReportLink(
            "Config run transitoire",
            artifact_paths["transient_config"],
            kind="toml",
        ),
        ReportLink(
            f"Config overview {context.site_label}",
            artifact_paths["overview_config"],
            kind="toml",
        ),
    )
    return BlockContent(links=links)


_CONTENT_BUILDERS: dict[str, Callable[[BlockBuildContext], BlockContent]] = {
    "site_context": _site_context_content,
    "hydraulic_properties": _hydraulic_properties_content,
    "spatial_context": _spatial_context_content,
    "hydrographic_network": _hydrographic_network_content,
    "simulation_network_outputs": _empty_content,
    "forcing_flux_context": _forcing_flux_content,
    "simulation_outputs": _simulation_outputs_content,
    "artifacts": _artifacts_content,
}


def _for_level(level: DetailLevel, items: Iterable[tuple[DetailLevel, Any]]) -> tuple[Any, ...]:
    return tuple(value for minimum, value in items if _level_at_least(level, minimum))


def _level_at_least(level: DetailLevel, minimum: DetailLevel) -> bool:
    return REPORT_LEVEL_RANK[level] >= REPORT_LEVEL_RANK[minimum]


def _block_variants_by_id(
    blocks_by_level: Mapping[DetailLevel, Sequence[ReportBlock]],
) -> tuple[tuple[str, dict[str, ReportBlock]], ...]:
    order: list[str] = []
    variants: dict[str, dict[str, ReportBlock]] = {}
    for level in REPORT_LEVELS:
        for block in blocks_by_level[level]:
            if block.block_id not in variants:
                order.append(block.block_id)
                variants[block.block_id] = {}
            variants[block.block_id][level] = block
    groups: list[tuple[str, dict[str, ReportBlock]]] = []
    for block_id in order:
        block_variants = variants[block_id]
        first_block = next(iter(block_variants.values()))
        complete_variants: dict[str, ReportBlock] = {}
        for level in REPORT_LEVELS:
            if level in block_variants:
                complete_variants[level] = block_variants[level]
            elif _level_at_least(level, first_block.level):
                complete_variants[level] = replace(first_block, level=level)
            else:
                complete_variants[level] = ReportBlock(
                    block_id=first_block.block_id,
                    title=first_block.title,
                    level=level,
                    status="empty",
                    lead=f"Bloc disponible a partir du niveau {first_block.level}.",
                )
        groups.append((block_id, complete_variants))
    return tuple(groups)


def _assert_monotonic_blocks(
    blocks_by_level: Mapping[DetailLevel, Sequence[ReportBlock]],
) -> None:
    for lower, higher in zip(REPORT_LEVELS, REPORT_LEVELS[1:], strict=False):
        lower_blocks = {block.block_id: block for block in blocks_by_level[lower]}
        higher_blocks = {block.block_id: block for block in blocks_by_level[higher]}
        for block_id, lower_block in lower_blocks.items():
            if block_id not in higher_blocks:
                raise RuntimeError(f"Block {block_id!r} missing from {higher} report.")
            lower_signature = _block_signature(lower_block)
            higher_signature = _block_signature(higher_blocks[block_id])
            for key, lower_items in lower_signature.items():
                missing = lower_items - higher_signature[key]
                if missing:
                    formatted = ", ".join(sorted(missing))
                    raise RuntimeError(
                        f"Block {block_id!r} is not monotonic from {lower} to {higher}: "
                        f"{key} missing {formatted}."
                    )


def _block_signature(block: ReportBlock) -> dict[str, set[str]]:
    return {
        "metrics": {metric.label for metric in block.metrics},
        "figures": {figure.figure_id for figure in block.figures},
        "tables": {table.table_id for table in block.tables},
        "links": {link.label for link in block.links},
        "warnings": set(block.warnings),
    }


def _figure(
    copied: dict[str, Path],
    figure_id: str,
    title: str,
    *,
    required: bool = True,
) -> ReportFigure:
    return ReportFigure(
        figure_id=figure_id,
        title=title,
        path=copied.get(figure_id),
        required=required,
    )


def _stats_rows(items: Iterable[tuple[str, dict[str, Any], str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, values, unit in items:
        if not values:
            continue
        rows.append(
            {
                "label": label,
                "rows": values.get("rows", ""),
                "start": values.get("start", ""),
                "end": values.get("end", ""),
                "mean": _fmt(values.get("mean")),
                "minimum": _fmt(values.get("minimum")),
                "maximum": _fmt(values.get("maximum")),
                "unit": unit,
            }
        )
    return rows


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _window(config: dict[str, Any]) -> str:
    start = config.get("start_datetime", "")
    end = config.get("end_datetime", "")
    step = config.get("step_value", "")
    if not start and not end:
        return "unknown"
    suffix = f", {step}" if step else ""
    return f"{start} -> {end}{suffix}"


def _unit_value(value: Any, unit: str) -> str:
    shown = _fmt(value)
    return f"{shown} {unit}".strip() if shown else ""


def _forcing_origin_label(config: dict[str, Any]) -> str:
    recharge_ids = ", ".join(
        str(item) for item in config.get("configured_recharge_station_ids", []) or []
    )
    runoff_ids = ", ".join(
        str(item) for item in config.get("configured_runoff_station_ids", []) or []
    )
    parts = []
    if recharge_ids:
        parts.append(f"recharge custom ({recharge_ids})")
    if runoff_ids:
        parts.append(f"runoff custom ({runoff_ids})")
    detail = "; ".join(parts) if parts else "forcages custom"
    return f"{detail}; fichiers exemples HydroModPy, pas une base nationale directe"


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.4g}"


build_blocks = _build_blocks
block_variants_by_id = _block_variants_by_id
assert_monotonic_blocks = _assert_monotonic_blocks
mapping = _mapping

__all__ = [
    "PAGE_MODES",
    "REPORT_LEVELS",
    "assert_monotonic_blocks",
    "block_variants_by_id",
    "build_blocks",
    "mapping",
]
