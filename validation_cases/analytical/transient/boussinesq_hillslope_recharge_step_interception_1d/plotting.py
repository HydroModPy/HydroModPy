"""Plotting helpers for the transient hillslope recharge-step interception case."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from validation_cases.shared.boussinesq_plotting import with_boussinesq_method_line

from .comparison import BoussinesqTransientHillslopeInterceptionComparison


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


def _nearest_index(values: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(np.asarray(values, dtype=float) - float(target))))


def plot_boussinesq_hillslope_recharge_step_interception_comparison(
    comparison: BoussinesqTransientHillslopeInterceptionComparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure comparing trajectory and selected profiles."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_cfg = dict(comparison.metadata.get("reference", {}))
    times_to_show = np.asarray(
        [
            0.0,
            comparison.analytical_onset_time_days,
            comparison.numerical_onset_time_days,
            comparison.final_elapsed_days,
        ],
        dtype=float,
    )
    selected_indices: list[int] = []
    for time_days in times_to_show:
        idx = _nearest_index(comparison.elapsed_days, time_days)
        if idx not in selected_indices:
            selected_indices.append(idx)
    colors = plt.cm.cividis(np.linspace(0.12, 0.88, len(selected_indices)))

    fig = plt.figure(figsize=(12.3, 8.4), dpi=dpi)
    grid = fig.add_gridspec(2, 2, height_ratios=(2.3, 1.35), hspace=0.34, wspace=0.24)
    ax_profiles = fig.add_subplot(grid[0, :])
    ax_traj = fig.add_subplot(grid[1, 0])
    ax_error = fig.add_subplot(grid[1, 1])

    ax_profiles.plot(
        comparison.x,
        comparison.topography_profile,
        color="0.35",
        lw=1.8,
        ls="--",
        label="Topography",
        zorder=1,
    )
    for color, index in zip(colors, selected_indices, strict=False):
        label = f"t={comparison.elapsed_days[index]:.0f} d"
        ax_profiles.plot(
            comparison.x,
            comparison.analytical_profiles[index],
            color=color,
            lw=2.0,
            label=f"{label} analytical",
            zorder=2,
        )
        ax_profiles.scatter(
            comparison.x,
            comparison.numerical_profiles[index],
            s=18,
            color=color,
            edgecolors="white",
            linewidths=0.45,
            label=f"{label} numerical",
            zorder=3,
        )
    ax_profiles.set_title("Selected profile snapshots")
    ax_profiles.set_xlabel("x [m]")
    ax_profiles.set_ylabel("Head / elevation [m]")
    ax_profiles.grid(True, ls=":", alpha=0.4)
    ax_profiles.legend(loc="best", ncol=2)

    ax_traj.plot(
        comparison.elapsed_days,
        comparison.analytical_interception_x_by_time,
        color="tab:orange",
        lw=2.2,
        label="Analytical approximation",
        zorder=2,
    )
    ax_traj.scatter(
        comparison.elapsed_days,
        comparison.numerical_interception_x_by_time,
        s=24,
        color="tab:blue",
        edgecolors="white",
        linewidths=0.5,
        label="Numerical trajectory",
        zorder=3,
    )
    ax_traj.axhline(
        comparison.inland_contact_threshold_x_m,
        color="0.25",
        lw=1.1,
        ls="--",
        label="Inland-contact threshold",
    )
    ax_traj.axvline(
        comparison.analytical_onset_time_days,
        color="tab:orange",
        lw=1.2,
        ls=":",
    )
    ax_traj.axvline(
        comparison.numerical_onset_time_days,
        color="tab:blue",
        lw=1.2,
        ls=":",
    )
    ax_traj.set_title("Interception trajectory")
    ax_traj.set_xlabel("Time [day]")
    ax_traj.set_ylabel("Interception x [m]")
    ax_traj.grid(True, ls=":", alpha=0.4)
    ax_traj.legend(loc="best")

    finite_mask = np.isfinite(comparison.numerical_interception_x_by_time) & np.isfinite(
        comparison.analytical_interception_x_by_time
    )
    x_error = (
        comparison.numerical_interception_x_by_time[finite_mask]
        - comparison.analytical_interception_x_by_time[finite_mask]
    )
    ax_error.axhline(0.0, color="0.25", lw=1.1, ls="--")
    ax_error.plot(
        comparison.elapsed_days[finite_mask],
        x_error,
        color="tab:blue",
        lw=1.8,
        marker="o",
        ms=4.0,
    )
    ax_error.set_title("Trajectory residual")
    ax_error.set_xlabel("Time [day]")
    ax_error.set_ylabel("x_num - x_ana [m]")
    ax_error.grid(True, ls=":", alpha=0.4)

    params_line = (
        f"L={float(reference_cfg['xmax']) - float(reference_cfg['xmin']):.0f} m   "
        f"slope={float(reference_cfg['topography_slope_m_per_m']):.4f} m/m   "
        f"h0={float(reference_cfg['base_head_m']):.2f} m   "
        f"R={float(reference_cfg['recharge_mm_day']):.1f} mm/day   "
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.1e} m/s   "
        f"Sy={float(reference_cfg['specific_yield']):.2f}"
    )
    metrics_line = (
        f"t_onset,ana={comparison.analytical_onset_time_days:.1f} d   "
        f"t_onset,num={comparison.numerical_onset_time_days:.1f} d   "
        f"|dt|={comparison.onset_time_error_days:.1f} d   "
        f"x-traj RMSE={comparison.trajectory_rmse_m:.2f} m   "
        f"x-traj max={comparison.trajectory_max_error_m:.2f} m   "
        f"row spread={comparison.row_spread:.2e} m"
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
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.32", "fc": "white", "ec": "0.75", "alpha": 0.95},
    )

    fig.suptitle(
        "Boussinesq Hillslope Recharge-Step Interception 1D Validation",
        fontsize=13,
    )
    fig.subplots_adjust(left=0.07, right=0.96, bottom=0.16, top=0.92, wspace=0.24, hspace=0.34)
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path
