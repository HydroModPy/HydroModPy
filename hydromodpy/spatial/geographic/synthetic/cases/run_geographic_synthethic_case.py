"""Run a synthetic geographic-only case from a dedicated TOML configuration."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import numpy as np

# Support direct execution from file path and ensure local package precedence.
repo_root = Path(__file__).resolve().parents[4]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.spatial.geographic.synthetic import (
    SyntheticGeographicConfig,
    build_synthetic_geographic,
)


def run_synthetic_geographic_case_from_toml(config_toml: str | Path):
    """Build one synthetic geographic runtime from its local TOML config."""
    config = SyntheticGeographicConfig.from_toml(config_toml)
    output_dir = Path(__file__).resolve().parent / "outputs" / config.case_id
    geographic = build_synthetic_geographic(
        config=config,
        output_dir=output_dir,
    )
    summary = {
        "case_id": str(config.case_id),
        "output_dir": str(output_dir),
        "watershed_shp": geographic.watershed_shp,
        "watershed_box_buff_dem": geographic.watershed_box_buff_dem,
        "shape": tuple(int(v) for v in geographic.surface_topo.as_array().shape),
        "elevation_min_m": float(np.min(geographic.surface_topo.as_array())),
        "elevation_mean_m": float(np.mean(geographic.surface_topo.as_array())),
        "elevation_max_m": float(np.max(geographic.surface_topo.as_array())),
        "catchment_area_km2": float(geographic.catch_area),
        "topography_kind": str(config.topography.kind),
        "right_to_left_amplitude": float(config.topography.right_to_left_amplitude),
    }
    return geographic, summary


def plot_synthetic_geographic_summary(
    geographic,
    output_dir: Path,
    *,
    case_id: str,
    topography_kind: str,
    show_plot: bool,
    vertical_exaggeration: float = 20.0,
) -> Path:
    """Plot one 3-D synthetic surface and one middle-row profile.

    The 3-D panel uses a configurable vertical exaggeration and draws the mesh
    directly on the surface to make very low-relief cases easier to read.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_path = output_dir / f"{case_id}_synthetic_geographic_summary.png"

    surface = geographic.surface_topo.as_array()
    xmin = float(geographic.xmin)
    xmax = float(geographic.xmax)
    ymin = float(geographic.ymin)
    ymax = float(geographic.ymax)
    mid_row = int(surface.shape[0] // 2)
    profile = surface[mid_row]
    x_profile = np.linspace(0.0, xmax - xmin, surface.shape[1], dtype=float)

    x_centers = xmin + (np.arange(surface.shape[1], dtype=float) + 0.5) * float(geographic.dem_res)
    y_centers = ymin + (np.arange(surface.shape[0], dtype=float) + 0.5) * float(geographic.dem_res)
    x_grid, y_grid = np.meshgrid(x_centers, y_centers)

    z_min = float(np.min(surface))
    z_max = float(np.max(surface))
    relief = z_max - z_min
    scaled_surface = z_min + (surface - z_min) * float(vertical_exaggeration)

    horizontal_span = max(xmax - xmin, ymax - ymin, 1.0)
    visible_relief = max(relief * float(vertical_exaggeration), 0.02 * horizontal_span)
    z_center = z_min + 0.5 * relief * float(vertical_exaggeration)
    z_lower = z_center - 0.5 * visible_relief
    z_upper = z_center + 0.5 * visible_relief

    fig = plt.figure(figsize=(8.2, 3.3), dpi=110)
    ax_surface = fig.add_subplot(1, 2, 1, projection="3d")
    ax_profile = fig.add_subplot(1, 2, 2)

    surf = ax_surface.plot_surface(
        x_grid,
        y_grid,
        scaled_surface,
        cmap="terrain",
        rstride=1,
        cstride=1,
        edgecolor="black",
        linewidth=0.35,
        antialiased=True,
        shade=False,
        alpha=0.95,
    )
    ax_surface.set_title(
        f"surface_topo 3D (VE x{vertical_exaggeration:.0f})",
        fontsize=8,
    )
    ax_surface.set_xlabel("x", fontsize=7, labelpad=2)
    ax_surface.set_ylabel("y", fontsize=7, labelpad=2)
    ax_surface.set_zlabel("elevation (scaled)", fontsize=7, labelpad=2)
    ax_surface.tick_params(labelsize=6, pad=1)
    ax_surface.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    ax_surface.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    ax_surface.set_xlim(xmin, xmax)
    ax_surface.set_ylim(ymin, ymax)
    ax_surface.set_zlim(z_lower, z_upper)
    ax_surface.view_init(elev=28, azim=-125)
    ax_surface.grid(True, lw=0.4, alpha=0.4)
    ax_surface.set_box_aspect((max(xmax - xmin, 1.0), max(ymax - ymin, 1.0), visible_relief))

    cbar = plt.colorbar(surf, ax=ax_surface, fraction=0.046, pad=0.08)
    cbar.ax.tick_params(labelsize=7)
    cbar.set_label("m", fontsize=8)

    ax_profile.plot(x_profile, profile, color="black", lw=2)
    ax_profile.set_title(f"middle-row profile ({topography_kind})", fontsize=8)
    ax_profile.set_xlabel("distance from left boundary (m)", fontsize=7)
    ax_profile.set_ylabel("elevation (m)", fontsize=7)
    ax_profile.tick_params(labelsize=6)
    ax_profile.grid(True, lw=0.4, alpha=0.4)

    fig.suptitle(
        "Synthetic geographic summary | "
        f"min={z_min:.2f} m | mean={np.mean(surface):.2f} m | max={z_max:.2f} m",
        fontsize=9,
    )
    fig.tight_layout(pad=0.35)
    fig.subplots_adjust(top=0.82)
    fig.savefig(fig_path, bbox_inches="tight", pad_inches=0.03)
    if show_plot:
        plt.show(block=True)
    else:
        plt.close(fig)
    return fig_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one synthetic geographic demo case and save a quick summary figure."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("run_geographic_synthethic_config.toml"),
        help="Path to a synthetic geographic TOML file.",
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not display figures interactively (still saves PNG files).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    geographic, summary = run_synthetic_geographic_case_from_toml(args.config)
    fig_path = plot_synthetic_geographic_summary(
        geographic,
        output_dir=Path(summary["output_dir"]),
        case_id=str(summary["case_id"]),
        topography_kind=str(summary["topography_kind"]),
        show_plot=(not bool(args.no_show_plot)),
    )

    print(f"[{summary['case_id']}] output_dir={summary['output_dir']}")
    print(f"[{summary['case_id']}] watershed_shp={summary['watershed_shp']}")
    print(f"[{summary['case_id']}] watershed_box_buff_dem={summary['watershed_box_buff_dem']}")
    print(f"[{summary['case_id']}] shape={summary['shape'][0]}x{summary['shape'][1]}")
    print(f"[{summary['case_id']}] catchment_area_km2={summary['catchment_area_km2']:.6f}")
    print(f"[{summary['case_id']}] elevation_min_m={summary['elevation_min_m']:.3f}")
    print(f"[{summary['case_id']}] elevation_mean_m={summary['elevation_mean_m']:.3f}")
    print(f"[{summary['case_id']}] elevation_max_m={summary['elevation_max_m']:.3f}")
    print(f"[{summary['case_id']}] figure={fig_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
