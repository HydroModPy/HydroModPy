"""Run one or multiple geographic-only cases from one TOML configuration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.ticker import ScalarFormatter

# Allow direct script execution without requiring editable install.
if __package__ in (None, ""):
    _repo_root = Path(__file__).resolve().parents[4]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

from hydromodpy.core.workspace import Workspace
from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig
from hydromodpy.spatial.geographic.cases.plotting_utils import (
    ensure_interactive_backend_for_show,
    show_figures_blocking,
)
from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation

REPO_ROOT = Path(__file__).resolve().parents[5]
KNOWN_CASE_IDS = ("base", "canut", "nancon", "aber")


def run_geographic_case_from_toml(config_toml: str | Path):
    """Build Workspace + Geographic from one global TOML file."""
    cfg = HydroModPyConfig.from_toml(config_toml)
    workspace = Workspace(config=cfg.workspace)
    geographic = CatchmentDelineation(config=cfg.geographic, initializing=workspace)
    return workspace, geographic


def _build_case_specs(cfg: HydroModPyConfig) -> dict[str, dict[str, Any]]:
    """Build default run specifications for all supported geographic demo cases."""
    default_snap = int(cfg.geographic.snap_dist) if cfg.geographic.snap_dist is not None else 50
    default_buff = float(cfg.geographic.buff_area) if cfg.geographic.buff_area is not None else 20.0
    canut_shp = REPO_ROOT / "examples" / "data" / "masks" / "canut.shp"
    wide_brittany_dem = REPO_ROOT / "examples" / "data" / "dem" / "DEM_armorican_massif.tif"

    return {
        "base": {
            "label": "Base outlet case (from TOML)",
            "overrides": {},
        },
        "canut": {
            "label": "Canut polygon case (from_polyg_shp)",
            "overrides": {
                "catch_def": "from_polyg_shp",
                "polyg_shp_path": canut_shp,
                "dem_init_path": wide_brittany_dem,
                "buff_area": default_buff,
            },
        },
        "nancon": {
            "label": "Nancon outlet case",
            "overrides": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": wide_brittany_dem,
                "x_outlet": 389285.910,
                "y_outlet": 6816518.749,
                "snap_dist": default_snap,
                "buff_area": default_buff,
            },
        },
        "aber": {
            "label": "Aber outlet case",
            "overrides": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": wide_brittany_dem,
                "x_outlet": 150727.164,
                "y_outlet": 6858066.520,
                "snap_dist": default_snap,
                "buff_area": default_buff,
            },
        },
    }


def _resolve_requested_cases(cases_arg: list[str]) -> list[str]:
    """Resolve requested case ids with support for the 'all' keyword."""
    if "all" in cases_arg:
        return list(KNOWN_CASE_IDS)
    ordered = []
    for case_id in cases_arg:
        if case_id not in ordered:
            ordered.append(case_id)
    return ordered


def _valid_dem_values(dem: np.ndarray, nodata: float | None) -> tuple[np.ndarray, np.ndarray]:
    """Return validity mask and valid DEM values for one raster array."""
    mask = np.isfinite(dem)
    if nodata is not None:
        mask &= dem != nodata
    return mask, dem[mask]


def _dem_distribution_metrics(
    values: np.ndarray,
    *,
    total_pixel_count: int,
    prefix: str,
) -> dict[str, float | int]:
    """Compute distribution metrics used in golden non-regression checks."""
    valid_count = int(values.size)
    nodata_count = int(total_pixel_count - valid_count)
    if valid_count == 0:
        return {
            f"valid_pixel_count_{prefix}": int(valid_count),
            f"nodata_pixel_count_{prefix}": int(nodata_count),
            f"mean_elevation_{prefix}_m": float("nan"),
            f"std_elevation_{prefix}_m": float("nan"),
            f"min_elevation_{prefix}_m": float("nan"),
            f"max_elevation_{prefix}_m": float("nan"),
            f"q05_elevation_{prefix}_m": float("nan"),
            f"q50_elevation_{prefix}_m": float("nan"),
            f"q95_elevation_{prefix}_m": float("nan"),
            f"sum_elevation_{prefix}_m": float("nan"),
        }

    return {
        f"valid_pixel_count_{prefix}": int(valid_count),
        f"nodata_pixel_count_{prefix}": int(nodata_count),
        f"mean_elevation_{prefix}_m": float(np.mean(values, dtype=np.float64)),
        f"std_elevation_{prefix}_m": float(np.std(values, dtype=np.float64)),
        f"min_elevation_{prefix}_m": float(np.min(values)),
        f"max_elevation_{prefix}_m": float(np.max(values)),
        f"q05_elevation_{prefix}_m": float(np.quantile(values, 0.05)),
        f"q50_elevation_{prefix}_m": float(np.quantile(values, 0.50)),
        f"q95_elevation_{prefix}_m": float(np.quantile(values, 0.95)),
        f"sum_elevation_{prefix}_m": float(np.sum(values, dtype=np.float64)),
    }


def compute_catchment_metrics(geographic) -> dict[str, float | int]:
    """Compute DEM-sensitive metrics for catchment and box-buffer footprints."""
    area_km2 = getattr(geographic, "catch_area", None)
    if area_km2 is None:
        gdf = gpd.read_file(geographic.watershed_shp)
        area_km2 = float(gdf.area.iloc[0]) / 1_000_000.0

    with rasterio.open(geographic.watershed_dem) as catch_src:
        catch_dem = catch_src.read(1)
        catch_nodata = catch_src.nodata
    catch_mask, catch_values = _valid_dem_values(catch_dem, catch_nodata)

    with rasterio.open(geographic.watershed_box_buff_dem) as box_src:
        box_dem = box_src.read(1)
        box_nodata = box_src.nodata
    box_mask, box_values = _valid_dem_values(box_dem, box_nodata)

    catch_metrics = _dem_distribution_metrics(
        catch_values,
        total_pixel_count=int(catch_dem.size),
        prefix="catchment",
    )
    box_metrics = _dem_distribution_metrics(
        box_values,
        total_pixel_count=int(box_dem.size),
        prefix="box_buff",
    )

    metrics = {
        "catchment_area_km2": float(area_km2),
        "mean_elevation_catchment_m": float(np.nanmean(np.where(catch_mask, catch_dem, np.nan))),
        "mean_elevation_box_buff_m": float(np.nanmean(np.where(box_mask, box_dem, np.nan))),
    }
    metrics.update(catch_metrics)
    metrics.update(box_metrics)
    return metrics


def run_geographic_cases_from_toml(
    config_toml: str | Path,
    *,
    case_ids: list[str] | None = None,
    show_plot: bool = True,
    outputs_root: Path | None = None,
    write_plot: bool = True,
) -> dict[str, dict[str, Any]]:
    """Run one or multiple geographic cases and return per-case summaries."""
    cfg = HydroModPyConfig.from_toml(config_toml)
    case_specs = _build_case_specs(cfg)
    selected_case_ids = case_ids or list(KNOWN_CASE_IDS)

    if "canut" in selected_case_ids:
        canut_path = Path(case_specs["canut"]["overrides"]["polyg_shp_path"]).resolve()
        if not canut_path.exists():
            raise FileNotFoundError(f"Canut shapefile not found at expected path: {canut_path}")

    resolved_outputs_root = outputs_root or (Path(__file__).resolve().parent / "outputs")
    summaries: dict[str, dict[str, Any]] = {}

    for case_id in selected_case_ids:
        spec = case_specs[case_id]
        case_label = str(spec["label"])
        geo_overrides = dict(spec["overrides"])

        case_project_root = cfg.workspace.project_root / f"{cfg.workspace.catch_name}_{case_id}"
        init_cfg = cfg.workspace.model_copy(update={"project_root": case_project_root})
        geo_cfg = cfg.geographic.model_copy(update=geo_overrides)

        workspace = Workspace(config=init_cfg)
        geographic = CatchmentDelineation(config=geo_cfg, initializing=workspace)
        metrics = compute_catchment_metrics(geographic)
        fig_path = None
        if write_plot:
            fig_path = _plot_geographic_summary(
                geographic,
                output_dir=resolved_outputs_root / case_id,
                case_id=case_id,
                case_label=case_label,
                metrics=metrics,
                show_plot=show_plot,
            )

        summaries[case_id] = {
            "case_label": case_label,
            "project_root": str(workspace.project_root),
            "watershed_shp": str(geographic.watershed_shp),
            "watershed_box_buff_dem": str(geographic.watershed_box_buff_dem),
            "shape_box_buff_dem": (
                int(geographic.dem_box_buff_data.shape[0]),
                int(geographic.dem_box_buff_data.shape[1]),
            ),
            "figure": None if fig_path is None else str(fig_path),
            **metrics,
        }

    return summaries


def _plot_geographic_summary(
    geographic,
    output_dir: Path,
    *,
    case_id: str,
    case_label: str,
    metrics: dict[str, float | int] | None = None,
    show_plot: bool,
) -> Path:
    """Save one quick validation figure (DEM + watershed polygon + outlet)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_path = output_dir / f"{case_id}_geographic_summary.png"
    if show_plot:
        ensure_interactive_backend_for_show()
    else:
        try:
            plt.switch_backend("Agg")
        except Exception:
            pass

    with rasterio.open(geographic.watershed_box_buff_dem) as src:
        dem = src.read(1)
        extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
        nodata = src.nodata

    fig, ax = plt.subplots(1, 1, figsize=(7.2, 5.4), dpi=120)
    im = ax.imshow(dem, extent=extent, cmap="terrain", origin="upper")
    cbar = plt.colorbar(im, ax=ax, fraction=0.042, pad=0.015)
    cbar.set_label("Elevation [m]", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    try:
        gdf = gpd.read_file(geographic.watershed_shp)
        gdf.boundary.plot(ax=ax, color="black", linewidth=1.2)
    except Exception as exc:
        ax.text(
            0.01,
            0.01,
            f"Could not load watershed_shp: {exc}",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=8,
            color="red",
        )

    outlet_handle = None
    if getattr(geographic, "catch_def", None) == "from_outlet_coord":
        if hasattr(geographic, "x_outlet") and hasattr(geographic, "y_outlet"):
            (outlet_handle,) = ax.plot(
                geographic.x_outlet,
                geographic.y_outlet,
                marker="^",
                markersize=8,
                color="green",
                markeredgecolor="black",
                label="Outlet",
            )

    if metrics is None:
        metrics = compute_catchment_metrics(geographic)
    area_km2 = metrics["catchment_area_km2"]
    mean_alt_catch = metrics["mean_elevation_catchment_m"]

    dem_mask = np.isfinite(dem)
    if nodata is not None:
        dem_mask &= dem != nodata
    mean_alt_domain = float(np.nanmean(np.where(dem_mask, dem, np.nan)))

    title = f"{case_label} | area={area_km2:.2f} km2"
    title += f"\nmean elevation box-buff={mean_alt_domain:.2f} m"
    title += f" | mean elevation catchment={mean_alt_catch:.2f} m"

    ax.set_title(title, fontsize=9)
    ax.set_xlabel("x [m]", fontsize=8)
    ax.set_ylabel("y [m]", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.ticklabel_format(style="plain", useOffset=False, axis="both")
    ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    if outlet_handle is not None:
        ax.legend([outlet_handle], ["Outlet"], loc="lower left", fontsize=8, framealpha=0.85)
    fig.tight_layout(pad=0.35)
    fig.savefig(fig_path, bbox_inches="tight", pad_inches=0.04)
    if show_plot:
        show_figures_blocking(fig)
    plt.close(fig)
    return fig_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one or multiple geographic-only pipelines from TOML "
            "(base + optional Canut/Nancon/Aber presets)."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("case_config.toml"),
        help="Path to a HydroModPy TOML file containing [workspace] and [geographic].",
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=("all",) + KNOWN_CASE_IDS,
        default=["all"],
        help=("Case ids to run sequentially. Use 'all' (default) for: base, canut, nancon, aber."),
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not display figures interactively (still saves PNG files).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    selected_case_ids = _resolve_requested_cases(args.cases)
    summaries = run_geographic_cases_from_toml(
        args.config,
        case_ids=selected_case_ids,
        show_plot=(not bool(args.no_show_plot)),
        outputs_root=Path(__file__).resolve().parent / "outputs",
    )
    for case_id in selected_case_ids:
        summary = summaries[case_id]
        print(f"[{case_id}] catch_folder={summary['catch_folder']}")
        print(f"[{case_id}] watershed_shp={summary['watershed_shp']}")
        print(f"[{case_id}] watershed_box_buff_dem={summary['watershed_box_buff_dem']}")
        print(
            f"[{case_id}] shape_box_buff_dem="
            f"{summary['shape_box_buff_dem'][0]}x{summary['shape_box_buff_dem'][1]}"
        )
        print(f"[{case_id}] catchment_area_km2={summary['catchment_area_km2']:.3f}")
        print(f"[{case_id}] mean_elevation_catchment_m={summary['mean_elevation_catchment_m']:.2f}")
        if summary["figure"] is not None:
            print(f"[{case_id}] figure={summary['figure']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
