"""
Quick visual test for SGrid_Generation.

This script uses the SGrid TOML/Pydantic interface directly:
    - TOML:   hydromodpy/grid/sgrid_config.toml
    - schema: hydromodpy/grid/sgrid_config.py

Run from repository root:
    python hydromodpy/grid/Test_hmp_refac_grid.py
    python hydromodpy/grid/Test_hmp_refac_grid.py --sgrid-config hydromodpy/grid/sgrid_config.toml
    python -m hydromodpy.grid.Test_hmp_refac_grid
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

# Import local modules without forcing `hydromodpy.__init__` on direct run.
if __package__ in (None, ""):
    GRID_DIR = os.path.dirname(os.path.realpath(__file__))
    if GRID_DIR not in sys.path:
        sys.path.insert(0, GRID_DIR)
    from sgrid_generation import SGrid_Generation
    from sgrid_config import load_sgrid_toml
else:
    from .sgrid_generation import SGrid_Generation
    from .sgrid_config import load_sgrid_toml


DEFAULT_SCENARIOS = [
    {
        "name": "constant_altitude + constant",
        "genmtd_bot": "constant_altitude",
        "zbot": -30.0,
        "genmtd_lay": "constant",
        "nlay": 5,
    },
    {
        "name": "constant_thickness + decay",
        "genmtd_bot": "constant_thickness",
        "thick": 200.0,
        "genmtd_lay": "decay",
        "nlay": 5,
        "lay_decay": 2.0,
    },
    {
        "name": "constant_thickness + constant",
        "genmtd_bot": "constant_thickness",
        "thick": 200.0,
        "genmtd_lay": "constant",
        "nlay": 5,
    },
    {
        "name": "constant_thickness + list",
        "genmtd_bot": "constant_thickness",
        "thick": 200.0,
        "genmtd_lay": "list",
        "lay_proportions": [0.1, 0.2, 0.3, 0.4],
    },
]


def _parse_args(default_sgrid_config: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and visualize structured grid scenarios."
    )
    parser.add_argument(
        "--sgrid-config",
        type=str,
        default=str(default_sgrid_config),
        help="Path to SGrid TOML configuration file.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory for generated PNG files (relative to TOML directory if relative).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=140,
        help="Figure DPI.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not display figures interactively.",
    )
    return parser.parse_args()


def _resolve_path(path_value: str, base_dir: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _masked(arr, nodata=-9999):
    """Return a masked array that hides no-data cells."""
    return np.ma.masked_where(arr <= nodata, arr)


def _to_nan(arr, nodata=-9999):
    """Convert no-data cells to NaN for 3D plotting."""
    out = np.array(arr, dtype=float, copy=True)
    out[out <= nodata] = np.nan
    return out


def _scenario_slug(name):
    """Normalize a scenario name into a filesystem-friendly slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _legend_style(n_items):
    """Compute legend size/layout from number of plotted lines."""
    fontsize = max(6.5, min(10.0, 11.0 - 0.45 * n_items))
    ncol = 1 if n_items <= 6 else 2
    return fontsize, ncol


def _build_scenario_grid(base_settings: dict, scenario: dict):
    """Build one structured grid scenario."""
    cfg = {
        "sgrid_type": base_settings["sgrid_type"],
        "lenuni": base_settings["lenuni"],
        "genmtd_top": base_settings["genmtd_top"],
        "top_path": base_settings["top_path"],
        "crs": base_settings.get("crs"),
        "nodata": base_settings["nodata"],
    }
    cfg.update({k: v for k, v in scenario.items() if k != "name"})
    sgrid = SGrid_Generation.from_config(cfg).run()
    return {
        "name": scenario["name"],
        "top": np.array(sgrid.top, copy=True),
        "botm": np.array(sgrid.botm, copy=True),
    }


def _plot_3d(ax_3d, top, botm):
    """Plot top + bottom surfaces and layer wireframes in 3D."""
    top_3d = _to_nan(top)
    bot_last_3d = _to_nan(botm[-1])
    nrow, ncol = top_3d.shape
    step = max(1, int(np.ceil(max(nrow, ncol) / 120)))

    top_ds = top_3d[::step, ::step]
    bot_last_ds = bot_last_3d[::step, ::step]
    yy, xx = np.mgrid[0 : top_ds.shape[0], 0 : top_ds.shape[1]]

    surf_top = ax_3d.plot_surface(
        xx,
        yy,
        top_ds,
        cmap="terrain",
        linewidth=0,
        antialiased=True,
        alpha=0.95,
    )
    ax_3d.plot_surface(
        xx,
        yy,
        bot_last_ds,
        cmap="viridis",
        linewidth=0,
        antialiased=True,
        alpha=0.55,
    )

    for k in range(botm.shape[0]):
        layer = _to_nan(botm[k])[::step, ::step]
        ax_3d.plot_wireframe(
            xx,
            yy,
            layer,
            rstride=5,
            cstride=5,
            linewidth=0.20,
            alpha=0.15,
            color="black",
        )

    ax_3d.view_init(elev=28, azim=-135)
    ax_3d.set_title("3D surfaces")
    ax_3d.set_xlabel("x (subsampled)")
    ax_3d.set_ylabel("y (subsampled)")
    ax_3d.set_zlabel("elevation [m]")
    return surf_top


def _plot_single_scenario(scenario, output_png, figure_size, save_dpi):
    """Create one figure for one scenario (map + section + 3D)."""
    top = _masked(scenario["top"])
    botm = scenario["botm"]
    nlay, _, ncol = botm.shape
    row = botm.shape[1] // 2
    x = np.arange(ncol)
    legend_fontsize, legend_ncol = _legend_style(nlay + 1)

    fig = plt.figure(figsize=figure_size, dpi=save_dpi)
    gs = fig.add_gridspec(nrows=1, ncols=3, width_ratios=[1.0, 1.2, 1.1])
    ax_map = fig.add_subplot(gs[0, 0])
    ax_cross = fig.add_subplot(gs[0, 1])
    ax_3d = fig.add_subplot(gs[0, 2], projection="3d")

    im = ax_map.imshow(top, origin="lower", cmap="terrain")
    ax_map.set_title("Top DEM")
    ax_map.set_xlabel("column index")
    ax_map.set_ylabel("row index")
    fig.colorbar(im, ax=ax_map, fraction=0.046, pad=0.04, label="elevation [m]")

    ax_cross.plot(x, top[row, :], color="black", linewidth=1.8, label="top")
    for k in range(nlay):
        ax_cross.plot(
            x,
            _masked(botm[k])[row, :],
            linewidth=1.1,
            alpha=0.9,
            label=f"botm L{k + 1}",
        )
    ax_cross.set_title(f"Center cross-section (row={row})")
    ax_cross.set_xlabel("column index")
    ax_cross.set_ylabel("elevation [m]")
    ax_cross.grid(True, alpha=0.25)
    ax_cross.legend(
        loc="best",
        fontsize=legend_fontsize,
        ncol=legend_ncol,
        title="Surfaces",
        title_fontsize=legend_fontsize,
        framealpha=0.9,
    )

    surf_top = _plot_3d(ax_3d, scenario["top"], botm)
    fig.colorbar(surf_top, ax=ax_3d, shrink=0.62, pad=0.08, label="elevation [m]")
    ax_3d.legend(
        handles=[
            Patch(facecolor="#9b7653", label="top surface"),
            Patch(facecolor="#4f9d69", label="bottom layer"),
        ],
        fontsize=legend_fontsize,
        loc="upper left",
    )

    fig.suptitle(f"Structured grid scenario: {scenario['name']}", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_png, bbox_inches="tight", dpi=save_dpi)
    print(f"Saved visualization to: {output_png}")


def _plot_scenarios(scenarios, output_dir, show_plots=True, figure_size=(15.8, 5.0), save_dpi=140):
    """Generate one figure per scenario."""
    for scenario in scenarios:
        slug = _scenario_slug(scenario["name"])
        output_png = os.path.join(output_dir, f"sgrid_generation_{slug}.png")
        _plot_single_scenario(
            scenario,
            output_png,
            figure_size=figure_size,
            save_dpi=save_dpi,
        )

    backend = plt.get_backend().lower()
    if show_plots and "agg" not in backend:
        plt.show()
    elif not show_plots:
        plt.close("all")


def main():
    cfolder = Path(os.path.dirname(os.path.realpath(__file__)))
    args = _parse_args(default_sgrid_config=cfolder / "sgrid_config.toml")

    sgrid_config_path = Path(args.sgrid_config).expanduser().resolve()
    sgrid_cfg = load_sgrid_toml(sgrid_config_path)
    config_dir = sgrid_config_path.parent

    output_dir = _resolve_path(args.output_dir, config_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_settings = {
        "sgrid_type": sgrid_cfg["sgrid_type"],
        "lenuni": sgrid_cfg["lenuni"],
        "genmtd_top": sgrid_cfg["genmtd_top"],
        "top_path": sgrid_cfg["top_path"],
        "crs": sgrid_cfg.get("crs"),
        "nodata": float(sgrid_cfg["nodata"]),
    }
    scenarios = [_build_scenario_grid(base_settings, s) for s in DEFAULT_SCENARIOS]

    _plot_scenarios(
        scenarios,
        output_dir=str(output_dir),
        show_plots=not args.no_show,
        figure_size=(15.8, 5.0),
        save_dpi=int(args.dpi),
    )
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
