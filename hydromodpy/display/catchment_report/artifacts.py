"""Artifact resolution for catchment reports."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.display.catchment_report.resources import (
    GEOLOGY_DATA_ROOT,
    REPO_ROOT,
)


@dataclass(frozen=True)
class ArtifactCandidate:
    root: str
    relative_path: str


@dataclass(frozen=True)
class ArtifactPathContext:
    context_assets: Path
    overview_figures: Path
    data_overview_figures: Path
    simulation_figures: Path

    def root_path(self, root: str) -> Path:
        roots = {
            "context_assets": self.context_assets,
            "overview_figures": self.overview_figures,
            "data_overview_figures": self.data_overview_figures,
            "simulation_figures": self.simulation_figures,
        }
        try:
            return roots[root]
        except KeyError as exc:
            raise ValueError(f"Unknown artifact root: {root!r}") from exc


@dataclass(frozen=True)
class ReportArtifactSpec:
    figure_id: str
    candidates: tuple[ArtifactCandidate, ...]

    def resolve(self, context: ArtifactPathContext) -> Path:
        candidates = [
            context.root_path(candidate.root) / candidate.relative_path
            for candidate in self.candidates
        ]
        return prefer(*candidates)


def artifact_candidate(
    root: str,
    relative_path: str,
) -> ArtifactCandidate:
    return ArtifactCandidate(root, relative_path)


def artifact_spec(
    figure_id: str,
    *candidates: ArtifactCandidate,
) -> ReportArtifactSpec:
    return ReportArtifactSpec(figure_id, candidates)


DEFAULT_ARTIFACT_SPECS: tuple[ReportArtifactSpec, ...] = (
    artifact_spec("identity_stats", artifact_candidate("overview_figures", "stats_card.png")),
    artifact_spec(
        "station_inventory",
        artifact_candidate("overview_figures", "station_inventory.png"),
    ),
    artifact_spec(
        "regional_context",
        artifact_candidate("overview_figures", "map_regional_context.png"),
        artifact_candidate("data_overview_figures", "map_regional_context.png"),
    ),
    artifact_spec("dem_context", artifact_candidate("overview_figures", "map_dem_context.png")),
    artifact_spec("dem_map", artifact_candidate("overview_figures", "map_dem.png")),
    artifact_spec("geology_map", artifact_candidate("overview_figures", "map_geology.png")),
    artifact_spec(
        "hydrography_map",
        artifact_candidate("overview_figures", "map_hydrography_data.png"),
        artifact_candidate("overview_figures", "map_hydrography.png"),
    ),
    artifact_spec(
        "climate_summary",
        artifact_candidate("overview_figures", "climatic_summary.png"),
    ),
    artifact_spec(
        "observed_discharge_overview",
        artifact_candidate("overview_figures", "timeseries_discharge.png"),
    ),
    artifact_spec(
        "observed_discharge_full",
        artifact_candidate("context_assets", "observed_discharge_full.png"),
    ),
    artifact_spec("forcing_window", artifact_candidate("context_assets", "forcing_window.png")),
    artifact_spec(
        "baseline_discharge_comparison",
        artifact_candidate("context_assets", "baseline_discharge_comparison.png"),
    ),
    artifact_spec(
        "network_comparison",
        artifact_candidate("context_assets", "hydrographic_network_comparison.png"),
    ),
    artifact_spec(
        "network_reference",
        artifact_candidate("context_assets", "hydrographic_network_reference.png"),
    ),
    artifact_spec(
        "network_generated",
        artifact_candidate("context_assets", "hydrographic_network_generated.png"),
    ),
    artifact_spec(
        "network_missing",
        artifact_candidate("context_assets", "hydrographic_network_reference_missing_only.png"),
    ),
    artifact_spec(
        "network_extra",
        artifact_candidate("context_assets", "hydrographic_network_generated_extra_only.png"),
    ),
    artifact_spec(
        "active_network_overlay",
        artifact_candidate(
            "simulation_figures",
            "simulated_active_network_reference_overlay.png",
        ),
    ),
    artifact_spec(
        "piezometric_map", artifact_candidate("simulation_figures", "piezometric_map.png")
    ),
    artifact_spec("seepage_map", artifact_candidate("simulation_figures", "seepage_map.png")),
    artifact_spec(
        "simulated_hydrograph",
        artifact_candidate("simulation_figures", "hydrograph.png"),
    ),
    artifact_spec("water_budget", artifact_candidate("simulation_figures", "water_budget.png")),
)

def copy_real_figures(
    figures_dir: Path,
    *,
    context_assets: Path,
    overview_figures: Path,
    data_overview_figures: Path,
    simulation_figures: Path,
    artifact_specs: Iterable[ReportArtifactSpec] = DEFAULT_ARTIFACT_SPECS,
) -> dict[str, Path]:
    context = ArtifactPathContext(
        context_assets=context_assets,
        overview_figures=overview_figures,
        data_overview_figures=data_overview_figures,
        simulation_figures=simulation_figures,
    )
    copied: dict[str, Path] = {}
    for spec in artifact_specs:
        source = spec.resolve(context)
        if not source.exists():
            continue
        target = figures_dir / source.name
        shutil.copy2(source, target)
        copied[spec.figure_id] = target
    return copied


def generate_generated_network_context_figure(
    copied: dict[str, Path],
    *,
    figures_dir: Path,
    config: dict[str, Any],
    generated_network_root: Path,
    geographic_scratch: Path,
) -> None:
    network_path = latest_generated_network_parquet(generated_network_root)
    dem_path = context_dem_path(config, geographic_scratch)
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
        outlet_xy=outlet_xy_from_config(config),
        relative_ticks=True,
        stream_label="Reseau genere DEM",
        title="Reseau genere DEM",
    )
    fig.tight_layout()
    target = figures_dir / "hydrographic_network_generated_context.png"
    fig.savefig(target, dpi=160)
    plt.close(fig)
    copied["network_generated"] = target


def latest_generated_network_parquet(generated_network_root: Path) -> Path | None:
    candidates = [
        path
        for path in generated_network_root.glob(
            "*/geographic_hydrographic_network_generated.parquet"
        )
        if path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def context_dem_path(config: dict[str, Any], geographic_scratch: Path) -> Path:
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


def outlet_xy_from_config(config: dict[str, Any]) -> tuple[float, float] | None:
    try:
        return (float(config["x_outlet"]), float(config["y_outlet"]))
    except Exception:
        return None


def geology_legend_rows(geographic_scratch: Path) -> tuple[Mapping[str, Any], ...]:
    geology_path = latest_geology_gpkg()
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

    code_field = first_present(geology, ("CODE_LEG", "code_leg", "CODE", "geology_code"))
    notation_field = first_present(geology, ("NOTATION", "notation", "LITHOLOGIE", "lithologie"))
    description_field = first_present(
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


def latest_geology_gpkg() -> Path | None:
    candidates = [
        path for path in GEOLOGY_DATA_ROOT.glob("geology_brgm_50k_*.gpkg") if path.is_file()
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


def first_present(frame: Any, names: Iterable[str]) -> str | None:
    columns = set(frame.columns)
    for name in names:
        if name in columns:
            return name
    return None


def prefer(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def write_manifest(
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
    expected_figure_ids: Iterable[str] = (),
) -> Path:
    manifest = output_dir / "block_report_manifest.json"
    payload = {
        "report_type": "real_figures_block_report",
        "source_note": (
            f"This report uses real {site_label} figures generated by the configured "
            "overview, context and simulation artifact producers."
        ),
        "expected_figure_ids": sorted(expected_figure_ids),
        "figure_ids": sorted(copied),
        "sources": {
            "context_summary": rel(context_summary),
            "context_assets": rel(context_assets),
            "overview_figures": rel(overview_figures),
            "data_overview_figures": rel(data_overview_figures),
            "simulation_figures": rel(simulation_figures),
            "geographic_scratch": rel(geographic_scratch),
            "generated_network_root": rel(generated_network_root),
        },
        "copied_figures": {key: rel(path) for key, path in sorted(copied.items())},
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def artifact_paths(
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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
