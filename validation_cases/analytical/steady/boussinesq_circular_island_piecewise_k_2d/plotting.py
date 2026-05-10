"""Plotting helpers for the steady circular-island piecewise-K validation case."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from validation_cases.shared.boussinesq_plotting import with_boussinesq_method_line

from .comparison import BoussinesqCircularIslandPiecewiseKComparison


def _enable_interactive_backend(show_plot: bool) -> bool:
    if not show_plot:
        return False

    backend = str(plt.get_backend()).lower()
    if "agg" not in backend:
        return True

    for candidate in ("QtAgg", "TkAgg"):
        try:
            plt.switch_backend(candidate)
        except Exception:
            continue
        return True

    print("Figure backend is non-interactive (Agg): figure saved but could not be displayed.")
    return False


def _font_sizes(fig) -> dict[str, float]:
    """Scale key font sizes from the current figure size."""
    scale = min(float(fig.get_figwidth()) / 11.0, float(fig.get_figheight()) / 8.0)
    return {
        "suptitle": 14.0 * scale,
        "axes_title": 11.5 * scale,
        "axes_label": 10.2 * scale,
        "ticks": 9.2 * scale,
        "legend": 8.1 * scale,
        "legend_title": 8.5 * scale,
        "metrics": 9.2 * scale,
    }


def plot_boussinesq_circular_island_piecewise_k_comparison(
    comparison: BoussinesqCircularIslandPiecewiseKComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing numerical and analytical radial heads."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_cfg = dict(comparison.metadata.get("reference", {}))
    profile_tol = dict(comparison.tolerances.get("radial_profile", {}))
    max_abs_tol = float(profile_tol.get("max_abs_error", 0.0))
    x_origin = float(reference_cfg["xmin"])
    y_origin = float(reference_cfg["ymin"])
    extent = [
        0.0,
        float(reference_cfg["length_x_m"]),
        0.0,
        float(reference_cfg["length_y_m"]),
    ]
    x_centers = np.asarray(comparison.x_centers, dtype=float) - x_origin
    y_centers = np.asarray(comparison.y_centers, dtype=float) - y_origin

    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.4), dpi=dpi)
    sizes = _font_sizes(fig)
    ax_dem, ax_head = axes[0]
    ax_profile, ax_residual = axes[1]
    sea_color = "#9fd0ea"
    shoreline_color = "#12354a"
    sea_layer = np.where(comparison.ocean_mask, 1.0, np.nan)
    sea_cmap = ListedColormap([sea_color])
    map_legend_handles = [
        Patch(facecolor=sea_color, edgecolor="none", label="Sea (ocean BC)"),
        Line2D([0], [0], color=shoreline_color, lw=1.4, label="Shoreline z = 0 m"),
    ]

    ax_dem.imshow(
        sea_layer,
        extent=extent,
        origin="lower",
        cmap=sea_cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
        zorder=0,
    )

    dem_image = ax_dem.imshow(
        np.where(comparison.land_mask, comparison.dem, np.nan),
        extent=extent,
        origin="lower",
        cmap="gist_earth",
        interpolation="nearest",
        zorder=1,
    )
    ax_dem.contour(
        x_centers,
        y_centers,
        comparison.dem,
        levels=[float(reference_cfg["sea_level_m"])],
        colors=shoreline_color,
        linewidths=1.2,
        zorder=2,
    )
    ax_dem.set_title("Synthetic DEM, sea, and shoreline", fontsize=sizes["axes_title"])
    ax_dem.set_xlabel("Local x [m]", fontsize=sizes["axes_label"])
    ax_dem.set_ylabel("Local y [m]", fontsize=sizes["axes_label"])
    dem_colorbar = fig.colorbar(dem_image, ax=ax_dem, shrink=0.88, label="Land elevation [m]")
    dem_colorbar.ax.tick_params(labelsize=sizes["ticks"])
    dem_colorbar.set_label("Land elevation [m]", size=sizes["axes_label"])
    ax_dem.legend(
        handles=map_legend_handles,
        loc="lower left",
        fontsize=sizes["legend"],
        title="Map Legend",
        title_fontsize=sizes["legend_title"],
        framealpha=0.95,
    )

    masked_heads = np.where(comparison.land_mask, comparison.heads, np.nan)
    ax_head.imshow(
        sea_layer,
        extent=extent,
        origin="lower",
        cmap=sea_cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
        zorder=0,
    )
    head_image = ax_head.imshow(
        masked_heads,
        extent=extent,
        origin="lower",
        cmap="viridis",
        interpolation="nearest",
        zorder=1,
    )
    ax_head.contour(
        x_centers,
        y_centers,
        comparison.dem,
        levels=[float(reference_cfg["sea_level_m"])],
        colors=shoreline_color,
        linewidths=1.2,
        zorder=2,
    )
    ax_head.set_title("Final water table on land, sea shown in blue", fontsize=sizes["axes_title"])
    ax_head.set_xlabel("Local x [m]", fontsize=sizes["axes_label"])
    ax_head.set_ylabel("Local y [m]", fontsize=sizes["axes_label"])
    head_colorbar = fig.colorbar(head_image, ax=ax_head, shrink=0.88, label="Head [m]")
    head_colorbar.ax.tick_params(labelsize=sizes["ticks"])
    head_colorbar.set_label("Head [m]", size=sizes["axes_label"])
    ax_head.legend(
        handles=map_legend_handles,
        loc="lower left",
        fontsize=sizes["legend"],
        title="Map Legend",
        title_fontsize=sizes["legend_title"],
        framealpha=0.95,
    )

    ax_profile.plot(
        comparison.annular_radius,
        comparison.analytical_profile,
        color="tab:orange",
        lw=2.2,
        label="Analytical radial profile",
        zorder=2,
    )
    ax_profile.scatter(
        comparison.annular_radius,
        comparison.numerical_profile,
        color="tab:blue",
        s=34,
        edgecolors="white",
        linewidths=0.6,
        label="Numerical annular mean",
        zorder=3,
    )
    ax_profile.set_title("Annular mean head profile", fontsize=sizes["axes_title"])
    ax_profile.set_xlabel("Radius [m]", fontsize=sizes["axes_label"])
    ax_profile.set_ylabel("Head [m]", fontsize=sizes["axes_label"])
    ax_profile.grid(True, ls=":", alpha=0.45)
    ax_profile.legend(loc="best", fontsize=sizes["legend"], framealpha=0.95)

    if max_abs_tol > 0.0:
        ax_residual.axhspan(
            -max_abs_tol,
            max_abs_tol,
            color="tab:green",
            alpha=0.12,
            label=f"Tolerance band +/-{max_abs_tol:.2f} m",
            zorder=1,
        )
    ax_residual.axhline(0.0, color="0.25", lw=1.2, ls="--", zorder=2)
    ax_residual.plot(
        comparison.annular_radius,
        comparison.residual_profile,
        color="tab:blue",
        lw=1.7,
        marker="o",
        ms=4.2,
        zorder=3,
        label="Residual (numerical - analytical)",
    )
    ax_residual.set_title("Radial-profile residual", fontsize=sizes["axes_title"])
    ax_residual.set_xlabel("Radius [m]", fontsize=sizes["axes_label"])
    ax_residual.set_ylabel("Residual [m]", fontsize=sizes["axes_label"])
    ax_residual.grid(True, ls=":", alpha=0.45)
    ax_residual.legend(loc="best", fontsize=sizes["legend"], framealpha=0.95)

    for axis in (ax_dem, ax_head, ax_profile, ax_residual):
        axis.tick_params(labelsize=sizes["ticks"])

    conductivity_values = ", ".join(
        f"{float(value):.1e}" for value in reference_cfg["hydraulic_conductivity_m_per_s_by_ring"]
    )
    params_line = (
        f"a={float(reference_cfg['island_radius_m']):.0f} m   "
        f"z_b={float(reference_cfg['substratum_elevation_m']):.2f} m   "
        f"z_top,max={float(reference_cfg['crest_elevation_m']):.2f} m   "
        f"R={float(reference_cfg['recharge_mm_day']):.2f} mm/day   "
        f"K_rings=[{conductivity_values}] m/s"
    )
    metrics_line = (
        f"timestep={comparison.timestep}   "
        f"RMSE={comparison.rms_error:.4f} m   "
        f"max abs error={comparison.max_error:.4f} m   "
        f"azimuthal spread={comparison.azimuthal_spread:.4f} m   "
        f"ocean head error={comparison.ocean_head_max_error:.2e} m   "
        f"min freeboard={comparison.land_clearance_min:.4f} m"
    )
    footer_lines = with_boussinesq_method_line(
        comparison.result,
        (params_line, metrics_line),
    )
    fig.text(
        0.5,
        0.01,
        "\n".join(footer_lines),
        ha="center",
        va="bottom",
        fontsize=sizes["metrics"],
        family="monospace",
        bbox={"boxstyle": "round,pad=0.32", "fc": "white", "ec": "0.75", "alpha": 0.95},
    )

    fig.suptitle(
        "Boussinesq Circular-Island Piecewise-K 2D Validation",
        fontsize=sizes["suptitle"],
    )
    fig.tight_layout(rect=[0.0, 0.08, 1.0, 0.95])
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path
