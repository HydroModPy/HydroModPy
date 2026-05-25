"""Build a block HTML report from real Nancon figures already in the repo."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.display.report_blocks import (  # noqa: E402
    DetailLevel,
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportMetric,
    ReportTable,
    key_value_table,
    write_report_page,
    write_report_page_with_block_variants,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "outputs" / "nancon_real_figures"
CONTEXT_ROOT = REPO_ROOT / "examples" / "projects" / "15_nancon_gauged_context" / "outputs"
CONTEXT_SUMMARY = CONTEXT_ROOT / "context" / "nancon_gauged_context_summary.json"
CONTEXT_ASSETS = CONTEXT_ROOT / "web" / "assets"
NANCON_PROJECT = REPO_ROOT / "examples" / "projects" / "02_nancon_watershed"
NANCON_GEOGRAPHIC_SCRATCH = NANCON_PROJECT / ".solver_scratch" / "_preprocessing" / "geographic"
GEOLOGY_DATA_ROOT = REPO_ROOT / "examples" / "data" / "geology"
OVERVIEW_FIGURES = REPO_ROOT / "examples" / "projects" / "02_nancon_watershed" / "figures" / "overview"
DATA_OVERVIEW_FIGURES = (
    REPO_ROOT / "examples" / "projects" / "05_nancon_data_overview" / "figures" / "overview"
)
SIMULATION_FIGURES = REPO_ROOT / "examples" / "projects" / "02_nancon_watershed" / "figures" / "transient_nwt"
DEFAULT_GENERATED_NETWORK_ROOT = NANCON_PROJECT / "simulations"
DEFAULT_CONTEXT_HTML = CONTEXT_ROOT / "web" / "index.html"
DEFAULT_OVERVIEW_STANDARD_HTML = NANCON_PROJECT / "web_review" / "standard" / "index.html"
DEFAULT_TRANSIENT_CONFIG = NANCON_PROJECT / "run_transient_nwt.toml"
DEFAULT_OVERVIEW_CONFIG = (
    REPO_ROOT / "examples" / "projects" / "05_nancon_data_overview" / "config_overview.toml"
)
GALLERY_GEO = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery" / "geographic"
GALLERY_SIM = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery" / "simulation"
REPORT_LEVELS: tuple[DetailLevel, ...] = ("compact", "standard", "audit")
REPORT_LEVEL_RANK = {level: index for index, level in enumerate(REPORT_LEVELS)}
PAGE_MODES = (*REPORT_LEVELS, "by_block")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--site-label", default="Nancon")
    parser.add_argument("--station-label", default="Nancon a Lecousse")
    parser.add_argument("--title", default="")
    parser.add_argument("--context-summary", type=Path, default=CONTEXT_SUMMARY)
    parser.add_argument("--context-assets", type=Path, default=CONTEXT_ASSETS)
    parser.add_argument("--overview-figures", type=Path, default=OVERVIEW_FIGURES)
    parser.add_argument("--data-overview-figures", type=Path, default=DATA_OVERVIEW_FIGURES)
    parser.add_argument("--simulation-figures", type=Path, default=SIMULATION_FIGURES)
    parser.add_argument("--geographic-scratch", type=Path, default=NANCON_GEOGRAPHIC_SCRATCH)
    parser.add_argument("--generated-network-root", type=Path, default=DEFAULT_GENERATED_NETWORK_ROOT)
    parser.add_argument("--context-html", type=Path, default=DEFAULT_CONTEXT_HTML)
    parser.add_argument("--overview-standard-html", type=Path, default=DEFAULT_OVERVIEW_STANDARD_HTML)
    parser.add_argument("--transient-config", type=Path, default=DEFAULT_TRANSIENT_CONFIG)
    parser.add_argument("--overview-config", type=Path, default=DEFAULT_OVERVIEW_CONFIG)
    parser.add_argument(
        "--allow-gallery-fallbacks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow Nancon documentation gallery fallbacks when a requested figure is absent.",
    )
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    title = args.title or f"{args.site_label} - rapport HTML par blocs avec figures reelles"
    web_dir = output_dir / "web"
    figures_dir = web_dir / "figures"
    if figures_dir.exists():
        shutil.rmtree(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)

    summary = _load_json(args.context_summary)
    config = _mapping(summary.get("configuration"))
    copied = _copy_real_figures(
        figures_dir,
        context_assets=args.context_assets,
        overview_figures=args.overview_figures,
        data_overview_figures=args.data_overview_figures,
        simulation_figures=args.simulation_figures,
        allow_gallery_fallbacks=args.allow_gallery_fallbacks,
    )
    _generate_generated_network_context_figure(
        copied,
        figures_dir=figures_dir,
        config=config,
        generated_network_root=args.generated_network_root,
        geographic_scratch=args.geographic_scratch,
    )
    manifest = _write_manifest(
        output_dir,
        copied,
        site_label=args.site_label,
        context_summary=args.context_summary,
        context_assets=args.context_assets,
        overview_figures=args.overview_figures,
        data_overview_figures=args.data_overview_figures,
        simulation_figures=args.simulation_figures,
        geographic_scratch=args.geographic_scratch,
        generated_network_root=args.generated_network_root,
        allow_gallery_fallbacks=args.allow_gallery_fallbacks,
    )
    artifact_paths = _artifact_paths(
        context_html=args.context_html,
        context_summary=args.context_summary,
        overview_standard_html=args.overview_standard_html,
        transient_config=args.transient_config,
        overview_config=args.overview_config,
    )
    geology_rows = _geology_legend_rows(args.geographic_scratch)
    level_links = {
        level: output_dir / "web_review" / level / "index.html" for level in PAGE_MODES
    }
    blocks_by_level = {
        level: _build_blocks(
            summary=summary,
            copied=copied,
            manifest=manifest,
            detail_level=level,
            site_label=args.site_label,
            station_label=args.station_label,
            geology_rows=geology_rows,
            artifact_paths=artifact_paths,
        )
        for level in REPORT_LEVELS
    }
    _assert_monotonic_blocks(blocks_by_level)
    block_variants = _block_variants_by_id(blocks_by_level)

    html_path = write_report_page(
        output_path=web_dir / "index.html",
        title=title,
        subtitle=_subtitle("standard", site_label=args.site_label),
        blocks=blocks_by_level["standard"],
        current_level="standard",
        level_links=level_links,
    )
    for level in REPORT_LEVELS:
        write_report_page(
            output_path=level_links[level],
            title=title,
            subtitle=_subtitle(level, site_label=args.site_label),
            blocks=blocks_by_level[level],
            current_level=level,
            level_links=level_links,
        )
    write_report_page_with_block_variants(
        output_path=level_links["by_block"],
        title=title,
        subtitle=_subtitle("by_block", site_label=args.site_label),
        block_variants=block_variants,
        current_level="by_block",
        default_level="standard",
        level_links=level_links,
    )
    print(html_path)
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _subtitle(level: str, *, site_label: str) -> str:
    labels = {
        "compact": "vue compacte",
        "standard": "vue standard",
        "audit": "vue audit",
        "by_block": "vue avec niveau choisi bloc par bloc",
    }
    return (
        f"Aggregation des figures {site_label} existantes: contexte jauge, hydrographie, "
        f"forcages, run transitoire de reference et artefacts associes - {labels.get(level, level)}."
    )


def _copy_real_figures(
    figures_dir: Path,
    *,
    context_assets: Path,
    overview_figures: Path,
    data_overview_figures: Path,
    simulation_figures: Path,
    allow_gallery_fallbacks: bool,
) -> dict[str, Path]:
    def gallery(primary: Path, fallback: Path) -> Path:
        return _prefer(primary, fallback) if allow_gallery_fallbacks else primary

    specs = {
        "identity_stats": _prefer(
            overview_figures / "stats_card.png",
            GALLERY_GEO / "geographic_nancon_identity_card_stats_card.png",
        )
        if allow_gallery_fallbacks
        else overview_figures / "stats_card.png",
        "station_inventory": _prefer(
            overview_figures / "station_inventory.png",
            GALLERY_GEO / "geographic_nancon_identity_card_station_inventory.png",
        )
        if allow_gallery_fallbacks
        else overview_figures / "station_inventory.png",
        "regional_context": data_overview_figures / "map_regional_context.png",
        "dem_context": overview_figures / "map_dem_context.png",
        "dem_map": _prefer(
            overview_figures / "map_dem.png",
            GALLERY_GEO / "geographic_nancon_identity_card_map_dem.png",
        )
        if allow_gallery_fallbacks
        else overview_figures / "map_dem.png",
        "geology_map": _prefer(
            overview_figures / "map_geology.png",
            GALLERY_GEO / "geographic_nancon_identity_card_map_geology.png",
        )
        if allow_gallery_fallbacks
        else overview_figures / "map_geology.png",
        "hydrography_map": _prefer(
            overview_figures / "map_hydrography_data.png",
            overview_figures / "map_hydrography.png",
            GALLERY_GEO / "geographic_nancon_identity_card_map_hydrography.png",
        )
        if allow_gallery_fallbacks
        else _prefer(overview_figures / "map_hydrography_data.png", overview_figures / "map_hydrography.png"),
        "climate_summary": _prefer(
            overview_figures / "climatic_summary.png",
            GALLERY_GEO / "geographic_nancon_identity_card_climatic_summary.png",
        )
        if allow_gallery_fallbacks
        else overview_figures / "climatic_summary.png",
        "observed_discharge_gallery": gallery(
            overview_figures / "timeseries_discharge.png",
            GALLERY_GEO / "geographic_nancon_timeseries_discharge.png",
        ),
        "observed_discharge_full": context_assets / "observed_discharge_full.png",
        "forcing_window": context_assets / "forcing_window.png",
        "baseline_discharge_comparison": context_assets / "baseline_discharge_comparison.png",
        "network_comparison": gallery(
            context_assets / "hydrographic_network_comparison.png",
            GALLERY_SIM / "nancon_transient_nwt_hydrographic_network_comparison.png",
        ),
        "network_reference": context_assets / "hydrographic_network_reference.png",
        "network_generated": context_assets / "hydrographic_network_generated.png",
        "network_missing": context_assets / "hydrographic_network_reference_missing_only.png",
        "network_extra": context_assets / "hydrographic_network_generated_extra_only.png",
        "active_network_overlay": gallery(
            simulation_figures / "simulated_active_network_reference_overlay.png",
            GALLERY_SIM / "nancon_transient_nwt_simulated_active_network_reference_overlay.png",
        ),
        "piezometric_map": gallery(
            simulation_figures / "piezometric_map.png",
            GALLERY_SIM / "nancon_transient_nwt_piezometric_map.png",
        ),
        "seepage_map": simulation_figures / "seepage_map.png",
        "simulated_hydrograph": gallery(
            simulation_figures / "hydrograph.png",
            GALLERY_SIM / "nancon_transient_nwt_hydrograph.png",
        ),
        "water_budget": gallery(
            simulation_figures / "water_budget.png",
            GALLERY_SIM / "nancon_transient_nwt_water_budget.png",
        ),
    }
    copied: dict[str, Path] = {}
    for figure_id, source in specs.items():
        if not source.exists():
            continue
        target = figures_dir / source.name
        shutil.copy2(source, target)
        copied[figure_id] = target
    return copied


def _generate_generated_network_context_figure(
    copied: dict[str, Path],
    *,
    figures_dir: Path,
    config: dict[str, Any],
    generated_network_root: Path,
    geographic_scratch: Path,
) -> None:
    network_path = _latest_generated_network_parquet(generated_network_root)
    dem_path = _context_dem_path(config, geographic_scratch)
    watershed_path = geographic_scratch / "watershed.shp"
    if network_path is None or not dem_path.exists() or not watershed_path.exists():
        return
    try:
        import geopandas as gpd
        import matplotlib
        import matplotlib.pyplot as plt
        import rasterio

        from hydromodpy.display.overview.panels import render_dem_map
    except Exception:
        return

    try:
        streams_gdf = gpd.read_parquet(network_path)
        with rasterio.open(dem_path) as src:
            target_crs = src.crs
        if target_crs is not None and streams_gdf.crs is not None:
            streams_gdf = streams_gdf.to_crs(target_crs)
    except Exception:
        return

    matplotlib.use("Agg")
    fig, ax = plt.subplots(figsize=(7, 6))
    render_dem_map(
        ax,
        dem_path=str(dem_path),
        watershed_shp=str(watershed_path),
        streams_gdf=streams_gdf,
        outlet_xy=_outlet_xy_from_config(config),
        relative_ticks=True,
        stream_label="Reseau genere DEM",
        title="Reseau genere DEM",
    )
    fig.tight_layout()
    target = figures_dir / "hydrographic_network_generated_context.png"
    fig.savefig(target, dpi=160)
    plt.close(fig)
    copied["network_generated"] = target


def _latest_generated_network_parquet(generated_network_root: Path) -> Path | None:
    candidates = [
        path
        for path in generated_network_root.glob("*/geographic_hydrographic_network_generated.parquet")
        if path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _context_dem_path(config: dict[str, Any], geographic_scratch: Path) -> Path:
    scratch_dem = geographic_scratch / "watershed_box_buff_dem.tif"
    if scratch_dem.exists():
        return scratch_dem
    dem_value = config.get("dem")
    if dem_value:
        dem_path = Path(str(dem_value))
        if not dem_path.is_absolute():
            dem_path = REPO_ROOT / dem_path
        return dem_path
    return scratch_dem


def _outlet_xy_from_config(config: dict[str, Any]) -> tuple[float, float] | None:
    try:
        return (float(config["x_outlet"]), float(config["y_outlet"]))
    except Exception:
        return None


def _geology_legend_rows(geographic_scratch: Path) -> tuple[Mapping[str, Any], ...]:
    geology_path = _latest_geology_gpkg()
    watershed_path = geographic_scratch / "watershed.shp"
    if geology_path is None:
        return ()
    try:
        import geopandas as gpd
        import pandas as pd
    except Exception:
        return ()
    try:
        geology = gpd.read_file(geology_path)
        if watershed_path.exists():
            watershed = gpd.read_file(watershed_path).to_crs(geology.crs)
            try:
                clipped = gpd.overlay(geology, watershed[["geometry"]], how="intersection")
            except Exception:
                geom = watershed.geometry.union_all()
                clipped = geology[geology.intersects(geom)].copy()
            geology = clipped
    except Exception:
        return ()
    if geology.empty:
        return ()

    code_field = _first_present(geology, ("CODE_LEG", "code_leg", "CODE", "geology_code"))
    notation_field = _first_present(geology, ("NOTATION", "notation", "LITHOLOGIE", "lithologie"))
    description_field = _first_present(
        geology,
        ("DESCR", "description", "NATURE", "LITHOLOGIE", "LITHO_SIMP", "lithologie"),
    )
    if code_field is None:
        return ()
    frame = geology.copy()
    frame["_code"] = frame[code_field].astype(str)
    frame["_notation"] = frame[notation_field].astype(str) if notation_field else ""
    frame["_description"] = frame[description_field].astype(str) if description_field else ""
    frame["_area_km2"] = frame.geometry.area / 1_000_000.0
    grouped = (
        frame.groupby(["_code", "_notation", "_description"], dropna=False)["_area_km2"]
        .sum()
        .reset_index()
    )
    grouped["_sort_code"] = pd.to_numeric(grouped["_code"], errors="coerce")
    grouped = grouped.sort_values(["_sort_code", "_code", "_notation"], na_position="last")
    rows: list[Mapping[str, Any]] = []
    for _, row in grouped.iterrows():
        rows.append(
            {
                "code": row["_code"],
                "notation": row["_notation"],
                "description": row["_description"],
                "area_km2": f"{float(row['_area_km2']):.2f}",
            }
        )
    return tuple(rows)


def _latest_geology_gpkg() -> Path | None:
    candidates = [
        path
        for path in GEOLOGY_DATA_ROOT.glob("geology_brgm_50k_*.gpkg")
        if path.is_file()
    ]
    if not candidates:
        candidates = [
            path
            for path in GEOLOGY_DATA_ROOT.glob("geology_brgm_1m_*.gpkg")
            if path.is_file() and path.name != "geology_brgm_1m_france.gpkg"
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _first_present(frame: Any, names: Iterable[str]) -> str | None:
    columns = set(frame.columns)
    for name in names:
        if name in columns:
            return name
    return None


def _prefer(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def _write_manifest(
    output_dir: Path,
    copied: dict[str, Path],
    *,
    site_label: str,
    context_summary: Path,
    context_assets: Path,
    overview_figures: Path,
    data_overview_figures: Path,
    simulation_figures: Path,
    geographic_scratch: Path,
    generated_network_root: Path,
    allow_gallery_fallbacks: bool,
) -> Path:
    manifest = output_dir / "block_report_manifest.json"
    payload = {
        "report_type": "real_figures_block_report",
        "source_note": (
            f"This report uses real {site_label} figures generated by the data-overview, "
            "gauged-context and transient NWT examples. It is not the synthetic smoke case."
        ),
        "figure_ids": sorted(copied),
        "sources": {
            "context_summary": _rel(context_summary),
            "context_assets": _rel(context_assets),
            "overview_figures": _rel(overview_figures),
            "data_overview_figures": _rel(data_overview_figures),
            "simulation_figures": _rel(simulation_figures),
            "geographic_scratch": _rel(geographic_scratch),
            "generated_network_root": _rel(generated_network_root),
            "gallery_geographic": _rel(GALLERY_GEO),
            "gallery_simulation": _rel(GALLERY_SIM),
        },
        "allow_gallery_fallbacks": allow_gallery_fallbacks,
        "copied_figures": {key: _rel(path) for key, path in sorted(copied.items())},
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def _artifact_paths(
    *,
    context_html: Path,
    context_summary: Path,
    overview_standard_html: Path,
    transient_config: Path,
    overview_config: Path,
) -> dict[str, Path]:
    return {
        "context_html": context_html,
        "context_summary": context_summary,
        "overview_standard_html": overview_standard_html,
        "transient_config": transient_config,
        "overview_config": overview_config,
    }


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
) -> list[ReportBlock]:
    config = _mapping(summary.get("configuration"))
    stats = _mapping(summary.get("stats"))
    baseline = _mapping(summary.get("baseline_run"))
    network = _mapping(summary.get("network"))

    blocks = [
        _site_context_block(
            config=config,
            baseline=baseline,
            copied=copied,
            detail_level=detail_level,
            site_label=site_label,
            station_label=station_label,
        ),
        _hydraulic_properties_block(config=config, detail_level=detail_level),
        _spatial_context_block(
            copied=copied,
            detail_level=detail_level,
            site_label=site_label,
            geology_rows=geology_rows,
        ),
        _hydrographic_network_block(
            network=network,
            copied=copied,
            detail_level=detail_level,
            site_label=site_label,
        ),
        _simulation_network_block(
            network=network,
            copied=copied,
            detail_level=detail_level,
            site_label=site_label,
        ),
        _forcing_flux_block(
            config=config,
            stats=stats,
            copied=copied,
            detail_level=detail_level,
            site_label=site_label,
        ),
        _simulation_outputs_block(
            config=config,
            stats=stats,
            baseline=baseline,
            copied=copied,
            detail_level=detail_level,
            site_label=site_label,
        ),
    ]
    if detail_level == "audit":
        blocks.append(
            _artifacts_block(manifest=manifest, site_label=site_label, artifact_paths=artifact_paths)
        )
    return blocks


def _site_context_block(
    *,
    config: dict[str, Any],
    baseline: dict[str, Any],
    copied: dict[str, Path],
    detail_level: DetailLevel,
    site_label: str,
    station_label: str,
) -> ReportBlock:
    metrics = _for_level(
        detail_level,
        (
            ("compact", ReportMetric("Site", station_label)),
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
    figures = _for_level(
        detail_level,
        (
            ("compact", _figure(copied, "identity_stats", "Carte d'identite observations")),
            ("standard", _figure(copied, "station_inventory", "Inventaire stations")),
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
    return ReportBlock(
        block_id="site_context",
        title="Site",
        level=detail_level,
        lead=(
            "Bloc d'identification du bassin jauge. Les figures viennent des sorties "
            "data-overview et non du smoke test synthetique."
        ),
        metrics=metrics,
        figures=figures,
        tables=_for_level(detail_level, (("standard", table),)),
    )


def _hydraulic_properties_block(
    *,
    config: dict[str, Any],
    detail_level: DetailLevel,
) -> ReportBlock:
    metrics = _for_level(
        detail_level,
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
    return ReportBlock(
        block_id="hydraulic_properties",
        title="Propriétés hydrauliques",
        level=detail_level,
        lead=(
            "Bloc generique des proprietes hydrauliques utilisees par le run de reference."
        ),
        metrics=metrics,
        tables=_for_level(detail_level, (("standard", table),)),
    )


def _spatial_context_block(
    *,
    copied: dict[str, Path],
    detail_level: DetailLevel,
    site_label: str,
    geology_rows: tuple[Mapping[str, Any], ...],
) -> ReportBlock:
    figures = _for_level(
        detail_level,
        (
            ("compact", _figure(copied, "regional_context", "Situation dans le Massif Armoricain")),
            ("compact", _figure(copied, "dem_context", "DEM, bassin versant et exutoire")),
            ("standard", _figure(copied, "geology_map", "Geologie du bassin")),
        ),
    )
    geology_table = ReportTable(
        "geology_units",
        "Codes geologiques presents",
        columns=(
            ("code", "Code"),
            ("notation", "Notation"),
            ("description", "Nature / description"),
            ("area_km2", "Surface approx. (km2)"),
        ),
        rows=geology_rows,
        empty_message="Aucun code geologique disponible.",
    )
    return ReportBlock(
        block_id="spatial_context",
        title="Contexte spatial: DEM et geologie",
        level=detail_level,
        lead=(
            "Bloc de lecture du support physique avant simulation: relief, contours "
            "du bassin et informations geologiques disponibles."
        ),
        figures=figures,
        tables=_for_level(detail_level, (("standard", geology_table),)) if geology_rows else (),
    )


def _hydrographic_network_block(
    *,
    network: dict[str, Any],
    copied: dict[str, Path],
    detail_level: DetailLevel,
    site_label: str,
) -> ReportBlock:
    metrics = _for_level(
        detail_level,
        (
            ("compact", ReportMetric("Segments BD Topage", network.get("reference_segments", "unknown"))),
            ("standard", ReportMetric("Seuil extraction DEM", "0.5", "km2")),
            ("audit", ReportMetric("Dossier figures source", network.get("figure_dir", "unknown"))),
        ),
    )
    figures = _for_level(
        detail_level,
        (
            ("compact", _figure(copied, "hydrography_map", "Reseau hydrographique BD Topage")),
            (
                "standard",
                _figure(copied, "network_generated", "Reseau genere DEM", required=False),
            ),
            (
                "audit",
                _figure(copied, "network_comparison", "Comparaison BD Topage / reseau derive DEM"),
            ),
            (
                "audit",
                _figure(copied, "network_missing", "Segments reference absents du genere", required=False),
            ),
            (
                "audit",
                _figure(copied, "network_extra", "Segments generes hors reference", required=False),
            ),
        ),
    )
    return ReportBlock(
        block_id="hydrographic_network",
        title="Reseau hydrographique observe et genere",
        level=detail_level,
        lead=(
            "Bloc central pour la future calibration naturelle: hydrographie de "
            "reference BD Topage, reseau genere depuis le DEM et differences locales. "
            "Le reseau DEM utilise ici un seuil d'aire contributive de 0.5 km2."
        ),
        metrics=metrics,
        figures=figures,
    )


def _simulation_network_block(
    *,
    network: dict[str, Any],
    copied: dict[str, Path],
    detail_level: DetailLevel,
    site_label: str,
) -> ReportBlock:
    figures = _for_level(
        detail_level,
        (
            (
                "standard",
                _figure(copied, "active_network_overlay", "Reseau actif simule vs reference"),
            ),
            ("compact", _figure(copied, "seepage_map", "Carte seepage simule", required=False)),
        ),
    )
    return ReportBlock(
        block_id="simulation_network_outputs",
        title="Simulation reseau actif et seepage",
        level=detail_level,
        lead=(
            "Bloc dependant des resultats de simulation: cellules actives, comparaison "
            "au reseau BD Topage et zones de seepage quand la figure est disponible."
        ),
        figures=figures,
    )


def _forcing_flux_block(
    *,
    config: dict[str, Any],
    stats: dict[str, Any],
    copied: dict[str, Path],
    detail_level: DetailLevel,
    site_label: str,
) -> ReportBlock:
    observed = _mapping(stats.get("observed_discharge"))
    recharge_ex04 = _mapping(stats.get("recharge_ex04"))
    recharge_nancon = _mapping(stats.get("recharge_nancon"))
    runoff_ex04 = _mapping(stats.get("runoff_ex04"))
    runoff_nancon = _mapping(stats.get("runoff_nancon"))
    rows = _stats_rows(
        (
            ("Debit observe", observed, "m3/s"),
            ("Recharge EX04", recharge_ex04, "mm/day"),
            ("Recharge NANCON", recharge_nancon, "mm/day"),
            ("Runoff EX04", runoff_ex04, "mm/day"),
            ("Runoff NANCON", runoff_nancon, "mm/day"),
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
    figures = _for_level(
        detail_level,
        (
            ("compact", _figure(copied, "forcing_window", "Fenetre 2000-2002: debit et forcages")),
            ("audit", _figure(copied, "observed_discharge_full", "Debit observe complet")),
            ("audit", _figure(copied, "climate_summary", "Monthly climatology")),
        ),
    )
    return ReportBlock(
        block_id="forcing_flux_context",
        title="Flux, debit observe et forcages",
        level=detail_level,
        lead=(
            "Bloc flux disponible avant tout lancement de modele: debit observe, "
            "recharge, runoff et contexte climatique."
        ),
        metrics=_for_level(
            detail_level,
            (
                ("compact", ReportMetric("Origine forcages", _forcing_origin_label(config))),
                ("compact", ReportMetric("Debit observe moyen", _fmt(observed.get("mean")), "m3/s")),
                ("audit", ReportMetric("Nombre de points debit observe", observed.get("rows", "unknown"))),
            ),
        ),
        figures=figures,
        tables=_for_level(detail_level, (("audit", table),)),
    )


def _simulation_outputs_block(
    *,
    config: dict[str, Any],
    stats: dict[str, Any],
    baseline: dict[str, Any],
    copied: dict[str, Path],
    detail_level: DetailLevel,
    site_label: str,
) -> ReportBlock:
    baseline_q = _mapping(stats.get("baseline_simulated_discharge"))
    metrics = _for_level(
        detail_level,
        (
            ("audit", ReportMetric("Solveur", "MODFLOW-NWT")),
            ("audit", ReportMetric("Pas temporels", baseline.get("n_timesteps", "unknown"))),
            ("audit", ReportMetric("Temps solveur", _fmt(baseline.get("runtime_seconds")), "s")),
            (
                "audit",
                ReportMetric(
                    "Debit simule moyen du run de reference",
                    _fmt(baseline_q.get("mean")),
                    "m3/s",
                ),
            ),
        ),
    )
    figures = _for_level(
        detail_level,
        (
            (
                "compact",
                _figure(
                    copied,
                    "baseline_discharge_comparison",
                    "Debits observes vs simules",
                ),
            ),
            ("standard", _figure(copied, "simulated_hydrograph", "Rapport des hydrographes")),
            ("audit", _figure(copied, "piezometric_map", "Carte de charge")),
            ("audit", _figure(copied, "water_budget", "Bilan en eau du bassin")),
        ),
    )
    return ReportBlock(
        block_id="simulation_outputs",
        title="Simulation flux",
        level=detail_level,
        lead=(
            "Bloc de simulation des flux: comparaison des debits, hydrographes, "
            "carte de charge et bilan en eau du run transitoire de reference."
        ),
        metrics=metrics,
        figures=figures,
    )


def _artifacts_block(
    *,
    manifest: Path,
    site_label: str,
    artifact_paths: dict[str, Path],
) -> ReportBlock:
    links = (
        ReportLink("Manifest du rapport blocs", manifest, kind="json"),
        ReportLink(f"Contexte jauge {site_label} HTML", artifact_paths["context_html"], kind="html"),
        ReportLink(
            f"Rapport {site_label} overview standard",
            artifact_paths["overview_standard_html"],
            kind="html",
        ),
        ReportLink("Resume contexte jauge", artifact_paths["context_summary"], kind="json"),
        ReportLink(
            "Config run transitoire",
            artifact_paths["transient_config"],
            kind="toml",
        ),
        ReportLink(
            f"Config overview {site_label}",
            artifact_paths["overview_config"],
            kind="toml",
        ),
    )
    return ReportBlock(
        block_id="artifacts",
        title="Artefacts et limites",
        level="audit",
        lead=(
            "Bloc audit: chemins sources et limites de cette page. Le rapport prouve "
            f"que la superstructure par blocs peut porter des figures {site_label} reelles; "
            "il ne ferme pas encore la calibration naturelle complete."
        ),
        links=links,
        warnings=(
            "Travail restant: fabriquer automatiquement observed_network_active_mask.npz "
            "et observed_network_distance_by_cell.npz sur un vrai maillage de calibration.",
            f"Travail restant: brancher de vrais runs candidats {site_label} sur "
            "score_natural_network_transient_candidate(...).",
        ),
    )


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
    for lower, higher in zip(REPORT_LEVELS, REPORT_LEVELS[1:]):
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
    recharge_ids = ", ".join(str(item) for item in config.get("configured_recharge_station_ids", []) or [])
    runoff_ids = ", ".join(str(item) for item in config.get("configured_runoff_station_ids", []) or [])
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


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
