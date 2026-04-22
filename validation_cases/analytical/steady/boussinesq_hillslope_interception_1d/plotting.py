"""Plotting helpers for the steady Boussinesq hillslope-interception case."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .comparison import BoussinesqHillslopeInterceptionComparison


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


def plot_boussinesq_hillslope_interception_comparison(
    comparison: BoussinesqHillslopeInterceptionComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing interception position and dry-zone heads."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_cfg = dict(comparison.metadata.get("reference", {}))
    tolerance_cfg = dict(comparison.tolerances.get("interception", {}))
    x_tol = float(tolerance_cfg.get("x_error_m", 0.0))
    dry_zone_mask = np.asarray(comparison.dry_zone_mask, dtype=bool)
    x_dry = comparison.x[dry_zone_mask]
    topography = comparison.topography_profile
    analytical_clearance = comparison.analytical_profile - topography
    numerical_clearance = comparison.numerical_profile - topography

    fig, (ax_profile, ax_clearance) = plt.subplots(
        2,
        1,
        figsize=(9.3, 7.0),
        dpi=dpi,
        sharex=True,
        gridspec_kw={"height_ratios": (3.1, 1.55)},
    )

    ax_profile.plot(
        comparison.x,
        topography,
        color="0.35",
        lw=1.8,
        ls="--",
        label="Topography",
        zorder=1,
    )
    ax_profile.plot(
        comparison.x,
        comparison.analytical_profile,
        color="tab:orange",
        lw=2.4,
        label="Analytical no-drain profile",
        zorder=2,
    )
    ax_profile.scatter(
        comparison.x,
        comparison.numerical_profile,
        s=34,
        color="tab:blue",
        edgecolors="white",
        linewidths=0.6,
        label="Numerical mean profile",
        zorder=3,
    )
    ax_profile.axvline(
        comparison.analytical_interception_x_m,
        color="tab:orange",
        lw=1.5,
        ls=":",
        label="Analytical interception",
    )
    ax_profile.axvline(
        comparison.numerical_interception_x_m,
        color="tab:blue",
        lw=1.5,
        ls=":",
        label="Numerical interception",
    )
    ax_profile.axvspan(
        float(x_dry[0]),
        float(comparison.analytical_interception_x_m),
        color="tab:green",
        alpha=0.08,
        zorder=0,
    )
    ax_profile.set_ylabel("Head / elevation [m]")
    ax_profile.set_title("Hillslope profile and interception position")
    ax_profile.grid(True, ls=":", alpha=0.45)
    ax_profile.legend(loc="best")

    if comparison.contact_tolerance_m > 0.0:
        ax_clearance.axhspan(
            -comparison.contact_tolerance_m,
            0.0,
            color="tab:red",
            alpha=0.12,
            label=(f"Numerical contact band [{-comparison.contact_tolerance_m:.2f}, 0.00] m"),
            zorder=1,
        )
    ax_clearance.axhline(0.0, color="0.25", lw=1.2, ls="--", zorder=2)
    ax_clearance.plot(
        comparison.x,
        analytical_clearance,
        color="tab:orange",
        lw=2.0,
        label="Analytical clearance",
        zorder=3,
    )
    ax_clearance.plot(
        comparison.x,
        numerical_clearance,
        color="tab:blue",
        lw=1.7,
        marker="o",
        ms=4.2,
        label="Numerical clearance",
        zorder=4,
    )
    if x_tol > 0.0:
        ax_clearance.axvspan(
            comparison.analytical_interception_x_m - x_tol,
            comparison.analytical_interception_x_m + x_tol,
            color="tab:green",
            alpha=0.08,
            zorder=0,
            label=f"Interception tolerance +/-{x_tol:.0f} m",
        )
    ax_clearance.set_xlabel("x [m]")
    ax_clearance.set_ylabel("Head - topo [m]")
    ax_clearance.set_title("Clearance above topography")
    ax_clearance.grid(True, ls=":", alpha=0.45)
    ax_clearance.legend(loc="best")

    params_line = (
        f"L={float(reference_cfg['xmax']) - float(reference_cfg['xmin']):.0f} m   "
        f"slope={float(reference_cfg['topography_slope_m_per_m']):.4f} m/m   "
        f"h_e={float(reference_cfg['east_head_m']):.2f} m   "
        f"R={float(reference_cfg['recharge_mm_day']):.1f} mm/day   "
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s"
    )
    metrics_line = (
        f"x_int,ana={comparison.analytical_interception_x_m:.2f} m   "
        f"x_int,num={comparison.numerical_interception_x_m:.2f} m   "
        f"|dx|={comparison.interception_x_error_m:.2f} m   "
        f"dry RMSE={comparison.dry_zone_rmse:.4f} m   "
        f"dry max={comparison.dry_zone_max_error:.4f} m   "
        f"row spread={comparison.row_spread:.2e} m"
    )
    fig.text(
        0.5,
        0.01,
        f"{params_line}\n{metrics_line}",
        ha="center",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.32", "fc": "white", "ec": "0.75", "alpha": 0.95},
    )

    fig.suptitle("Boussinesq Hillslope Interception 1D Validation", fontsize=13)
    fig.tight_layout(rect=[0.0, 0.10, 1.0, 0.95])
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path
