"""Plotting helpers for the steady Dupuit seepage-limit validation case."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .comparison import SeepageLimitComparison


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


def plot_seepage_limit_comparison(
    comparison: SeepageLimitComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure of the hillslope profile and its seepage limit."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    x = comparison.x_m
    topography = comparison.topography[0]
    watertable = comparison.watertable[0]
    seeping = comparison.seepage_mask[0]

    fig, (ax_profile, ax_excess) = plt.subplots(
        2,
        1,
        figsize=(9.2, 6.8),
        dpi=dpi,
        sharex=True,
        gridspec_kw={"height_ratios": (3.0, 1.35)},
    )

    ax_profile.fill_between(
        x,
        0.0,
        topography,
        where=seeping,
        color="tab:cyan",
        alpha=0.22,
        step="mid",
        label="Numerical seepage mask",
        zorder=1,
    )
    ax_profile.plot(x, topography, color="0.35", lw=2.0, label="Land surface", zorder=2)
    ax_profile.plot(
        x,
        comparison.analytical_head_profile,
        color="tab:orange",
        lw=2.4,
        label="Analytical Dupuit water table",
        zorder=3,
    )
    ax_profile.scatter(
        x,
        watertable,
        s=22,
        color="tab:blue",
        edgecolors="white",
        linewidths=0.5,
        label="Numerical water table",
        zorder=4,
    )
    ax_profile.axvline(
        comparison.analytical_seepage_limit_m,
        color="tab:orange",
        ls="--",
        lw=1.6,
        label=f"Closed-form limit x_e={comparison.analytical_seepage_limit_m:.1f} m",
        zorder=5,
    )
    ax_profile.axvline(
        comparison.numerical_seepage_limit_m,
        color="tab:blue",
        ls=":",
        lw=1.8,
        label=f"Mask limit {comparison.numerical_seepage_limit_m:.1f} m",
        zorder=5,
    )
    ax_profile.set_ylabel("Elevation [m]")
    ax_profile.set_title("Hillslope profile and seepage limit")
    ax_profile.grid(True, ls=":", alpha=0.45)
    ax_profile.legend(loc="upper left", fontsize=8)

    excess = watertable - topography
    ax_excess.axhline(0.0, color="0.25", lw=1.2, ls="--", zorder=2)
    ax_excess.plot(x, excess, color="tab:blue", lw=1.7, marker="o", ms=3.4, zorder=3)
    ax_excess.set_xlabel("x from the toe [m]")
    ax_excess.set_ylabel("Water table - surface [m]")
    ax_excess.set_title("Surface excess (positive where the drain discharges), zoomed on zero")
    zoom = max(float(np.max(excess)), 1e-6)
    ax_excess.set_ylim(-6.0 * zoom, 3.0 * zoom)
    ax_excess.grid(True, ls=":", alpha=0.45)

    params_line = (
        f"L={comparison.hillslope_length_m:.0f} m   "
        f"slope={comparison.slope:.3f}   "
        f"K={comparison.hydraulic_conductivity_m_per_s:.3e} m/s   "
        f"R={comparison.recharge_m_per_s:.3e} m/s   "
        f"K/R={comparison.conductivity_over_recharge:.4g}"
    )
    metrics_line = (
        f"solver={comparison.solver}   "
        f"limit error={comparison.seepage_limit_error_m:.3f} m   "
        f"head max abs error={comparison.head_profile_max_error_m:.5f} m   "
        f"drain outflow={comparison.drain_outflow_m3_per_s:.4e} m3/s"
    )
    fig.text(
        0.5,
        0.01,
        "\n".join((params_line, metrics_line)),
        ha="center",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.32", "fc": "white", "ec": "0.75", "alpha": 0.95},
    )

    fig.suptitle("Dupuit Seepage-Limit 1D Validation", fontsize=13)
    fig.tight_layout(rect=[0.0, 0.10, 1.0, 0.95])
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path


__all__ = ["plot_seepage_limit_comparison"]
