"""Run one reference geographic case focused on hydrographic network extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import ScalarFormatter
import numpy as np
import rasterio

# Support direct execution from file path and ensure local package precedence.
repo_root = Path(__file__).resolve().parents[4]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.geographic.cases.plotting_utils import (
    ensure_interactive_backend_for_show,
    show_figures_blocking,
)
from hydromodpy.geographic.cases import run_geographic_case_from_toml


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _build_reference_figure(
    *,
    geographic,
    summary: dict[str, Any],
):
    with rasterio.open(geographic.watershed_box_buff_dem) as src:
        dem = np.asarray(src.read(1), dtype=float)
        nodata = src.nodata
        extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)

    valid_mask = np.isfinite(dem)
    if nodata is not None:
        valid_mask &= dem != nodata
    dem_display = np.where(valid_mask, dem, np.nan)

    watershed = gpd.read_file(geographic.watershed_shp)
    network = gpd.read_file(geographic.river_network_shp)

    fig, ax = plt.subplots(1, 1, figsize=(11.5, 8.5), dpi=130)
    im = ax.imshow(
        dem_display,
        extent=extent,
        cmap="terrain",
        origin="upper",
        interpolation="nearest",
    )
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.015)
    cbar.set_label("Topography [m]", fontsize=10)
    cbar.ax.tick_params(labelsize=9)

    watershed.boundary.plot(ax=ax, color="black", linewidth=1.8, zorder=5)
    if not network.empty:
        network.plot(ax=ax, color="#1f77b4", linewidth=1.4, zorder=6)

    outlet_x = getattr(geographic, "x_outlet", None)
    outlet_y = getattr(geographic, "y_outlet", None)
    if outlet_x is not None and outlet_y is not None:
        ax.plot(
            float(outlet_x),
            float(outlet_y),
            marker="^",
            markersize=9.5,
            color="#2ca02c",
            markeredgecolor="black",
            zorder=7,
        )

    length_km = float(summary["network_total_length_m"]) / 1000.0
    drainage_density = float(summary["drainage_density_km_per_km2"])
    threshold_mode = str(summary["threshold_mode"])
    threshold_value = float(summary["threshold_value"])
    threshold_cells = float(summary["threshold_cells"])
    title = "Nançon | Réseau hydrographique extrait du DEM"
    subtitle = (
        f"segments={int(summary['segment_count'])} | longueur={length_km:.2f} km | "
        f"densité={drainage_density:.3f} km/km2"
    )
    threshold_line = (
        f"mode={threshold_mode} | seuil={threshold_value:.3f} km2 | "
        f"equiv_cells={threshold_cells:.1f}"
    )
    ax.set_title(f"{title}\n{subtitle}\n{threshold_line}", fontsize=11)

    handles = [
        Line2D([0], [0], color="black", linewidth=1.8, label="Bassin versant"),
        Line2D([0], [0], color="#1f77b4", linewidth=1.4, label="Réseau hydrographique"),
        Line2D(
            [0],
            [0],
            marker="^",
            linestyle="None",
            markerfacecolor="#2ca02c",
            markeredgecolor="black",
            markersize=8.0,
            label="Exutoire",
        ),
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=9, framealpha=0.9)
    ax.set_xlabel("x [m]", fontsize=10)
    ax.set_ylabel("y [m]", fontsize=10)
    ax.tick_params(labelsize=9)
    ax.ticklabel_format(style="plain", useOffset=False, axis="both")
    ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    fig.tight_layout(pad=0.6)
    return fig


def run_reference_river_network_nancon_from_toml(
    config_toml: str | Path,
    *,
    output_dir: str | Path | None = None,
    show_plot: bool = True,
) -> dict[str, object]:
    """Run one Nançon geographic preprocessing case with river-network outputs."""
    config_path = Path(config_toml).expanduser().resolve()
    workspace, geographic = run_geographic_case_from_toml(config_path)

    network_shp = Path(geographic.river_network_shp).expanduser().resolve()
    summary_json = Path(geographic.river_network_summary_json).expanduser().resolve()
    if not network_shp.exists():
        raise FileNotFoundError(
            f"Missing river network shapefile: {network_shp}. "
            "Ensure [geographic.river_network].enabled=true in the config."
        )
    if not summary_json.exists():
        raise FileNotFoundError(
            f"Missing river network summary json: {summary_json}. "
            "Ensure [geographic.river_network].enabled=true in the config."
        )

    summary = _read_json(summary_json)
    out_dir = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else Path(__file__).resolve().parent / "outputs"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "nancon_river_network_overview.png"

    if show_plot:
        ensure_interactive_backend_for_show()
    fig = _build_reference_figure(geographic=geographic, summary=summary)
    fig.savefig(fig_path, bbox_inches="tight", pad_inches=0.05)
    if show_plot:
        show_figures_blocking(fig)
    plt.close(fig)

    return {
        "catch_folder": str(workspace.catch_folder),
        "watershed_shp": str(geographic.watershed_shp),
        "watershed_box_buff_dem": str(geographic.watershed_box_buff_dem),
        "river_network_shp": str(network_shp),
        "river_network_summary_json": str(summary_json),
        "segment_count": int(summary["segment_count"]),
        "network_total_length_m": float(summary["network_total_length_m"]),
        "figure": str(fig_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one reference geographic case on Nançon and show topography, "
            "watershed boundary, and extracted hydrographic network."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("case_config_river_network_nancon.toml"),
        help="Path to one HydroModPy TOML file for this case.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory where output figures are saved.",
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not display the figure interactively (still saves the PNG).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = run_reference_river_network_nancon_from_toml(
        args.config,
        output_dir=args.output_dir,
        show_plot=(not bool(args.no_show_plot)),
    )
    print(f"catch_folder={payload['catch_folder']}")
    print(f"river_network_shp={payload['river_network_shp']}")
    print(f"river_network_summary_json={payload['river_network_summary_json']}")
    print(f"segment_count={payload['segment_count']}")
    print(f"network_total_length_m={payload['network_total_length_m']:.3f}")
    print(f"figure={payload['figure']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
