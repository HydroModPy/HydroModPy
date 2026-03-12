"""Plotting helpers for the steady Dupuit uniform-recharge validation case."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from .comparison import DupuitUniformRechargeComparison


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


def plot_dupuit_uniform_recharge_comparison(
    comparison: DupuitUniformRechargeComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing the numerical and analytical head profiles."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_cfg = dict(comparison.metadata.get("reference", {}))
    head_profile_tol = dict(comparison.tolerances.get("head_profile", {}))
    max_abs_tol = float(head_profile_tol.get("max_abs_error", 0.0))
    recharge_mm_day = float(reference_cfg["recharge_mm_day"])
    domain_length = float(reference_cfg["xmax"]) - float(reference_cfg["xmin"])
    params_line = (
        f"L={domain_length:.0f} m   "
        f"h_w={float(reference_cfg['west_head']):.2f} m   "
        f"h_e={float(reference_cfg['east_head']):.2f} m   "
        f"R={recharge_mm_day:.2f} mm/day   "
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"b={float(reference_cfg['aquifer_thickness_m']):.1f} m"
    )

    fig, (ax_profile, ax_residual) = plt.subplots(
        2,
        1,
        figsize=(9.2, 6.8),
        dpi=dpi,
        sharex=True,
        gridspec_kw={"height_ratios": (3.0, 1.35)},
    )

    ax_profile.plot(
        comparison.x,
        comparison.analytical_profile,
        color="tab:orange",
        lw=2.4,
        label="Analytical Dupuit profile",
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
    ax_profile.set_ylabel("Head [m]")
    ax_profile.set_title("Numerical and analytical water-table profiles")
    ax_profile.grid(True, ls=":", alpha=0.45)
    ax_profile.legend(loc="best")

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
        comparison.x,
        comparison.residual_profile,
        color="tab:blue",
        lw=1.7,
        marker="o",
        ms=4.4,
        label="Residual (numerical - analytical)",
        zorder=3,
    )
    ax_residual.set_xlabel("x [m]")
    ax_residual.set_ylabel("Residual [m]")
    ax_residual.set_title("Profile residual")
    ax_residual.grid(True, ls=":", alpha=0.45)
    ax_residual.legend(loc="best")

    metrics_line = (
        f"timestep={comparison.timestep}   "
        f"RMSE={comparison.rms_error:.4f} m   "
        f"max abs error={comparison.max_error:.4f} m   "
        f"cross-row spread={comparison.row_spread:.2e} m"
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

    fig.suptitle("Dupuit Uniform-Recharge 1D Validation", fontsize=13)
    fig.tight_layout(rect=[0.0, 0.10, 1.0, 0.95])
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path
