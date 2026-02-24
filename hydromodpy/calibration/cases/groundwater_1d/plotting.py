"""
Plotting helpers for the transient 1D groundwater calibration case.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _extract_columns_at_nodes(values_matrix, node_indices, target_nodes):
    """
    Extract columns from `values_matrix` corresponding to requested node IDs.
    """
    node_indices = np.asarray(node_indices, dtype=int).ravel()
    target_nodes = np.asarray(target_nodes, dtype=int).ravel()
    out = np.empty((values_matrix.shape[0], target_nodes.size), dtype=float)
    for j, node in enumerate(target_nodes):
        column = int(np.argmin(np.abs(node_indices - int(node))))
        out[:, j] = values_matrix[:, column]
    return out


def plot_calibration_result(chronicle, calibration, output_png, show_plot=True):
    """
    Plot and save one groundwater calibration summary figure.
    """
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    t = np.asarray(chronicle["t"], dtype=float)
    x = np.asarray(chronicle["x"], dtype=float)
    h_true = np.asarray(chronicle["h_true"], dtype=float)
    h_best = np.asarray(calibration["simulation_best"]["h"], dtype=float)
    recharge_series = np.asarray(chronicle["recharge_series"], dtype=float)
    obs_time = np.asarray(chronicle["obs_time_days"], dtype=float)
    obs_noisy = np.asarray(chronicle["obs_noisy_matrix"], dtype=float)
    midpoint_nodes = np.asarray(chronicle["midpoint_node_indices"], dtype=int)
    midpoint_x = np.asarray(chronicle["midpoint_x_m"], dtype=float)
    obs_nodes = np.asarray(chronicle["obs_node_indices"], dtype=int)

    metrics = calibration["metrics"]
    params_true = calibration["params_true"]
    params_best = calibration["params_best"]
    result = calibration["result"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), dpi=140)
    ax_ts, ax_profile = axes.ravel()

    # Graph 1: heads at zone midpoints + forcing on right axis.
    colors = ("tab:blue", "tab:orange")
    labels = ("upstream zone midpoint", "downstream zone midpoint")
    for j, (xj, color, label) in enumerate(zip(midpoint_x, colors, labels)):
        idx = int(midpoint_nodes[j])
        ax_ts.plot(t, h_true[:, idx], color=color, lw=2.0, label=f"True head ({label}, x={xj:.1f} m)")
        ax_ts.plot(
            t,
            h_best[:, idx],
            color=color,
            lw=1.8,
            ls="--",
            label=f"Calibrated head ({label})",
        )

    midpoint_obs = _extract_columns_at_nodes(obs_noisy, obs_nodes, midpoint_nodes)
    for j, (xj, color) in enumerate(zip(midpoint_x, colors)):
        ax_ts.scatter(
            obs_time,
            midpoint_obs[:, j],
            s=20,
            color=color,
            alpha=0.55,
            marker="o",
            label=f"Noisy obs midpoint x={xj:.1f} m",
        )

    ax_ts.set_xlabel("Time [day]")
    ax_ts.set_ylabel("Head [m]")
    ax_ts.set_title("Heads at zone midpoints")
    ax_ts.grid(True, ls=":", alpha=0.45)

    ax_ts_right = ax_ts.twinx()
    ax_ts_right.plot(
        t,
        recharge_series,
        color="tab:green",
        lw=1.8,
        ls="-.",
        label="Recharge forcing R(t)",
    )
    ax_ts_right.set_ylabel("Recharge [m/day]", color="tab:green")
    ax_ts_right.tick_params(axis="y", labelcolor="tab:green")

    left_handles, left_labels = ax_ts.get_legend_handles_labels()
    right_handles, right_labels = ax_ts_right.get_legend_handles_labels()
    ax_ts.legend(left_handles + right_handles, left_labels + right_labels, fontsize=7, loc="best")

    # Graph 2: h(x) profiles at several times.
    profile_times = np.linspace(0, t.size - 1, 5, dtype=int)
    profile_times = np.unique(profile_times)
    cmap = plt.get_cmap("plasma")
    for k, it in enumerate(profile_times):
        color = cmap(k / max(profile_times.size - 1, 1))
        t_value = float(t[it])
        ax_profile.plot(
            x,
            h_true[it],
            color=color,
            lw=2.0,
            label=f"True t={t_value:.0f} d",
        )
        ax_profile.plot(
            x,
            h_best[it],
            color=color,
            lw=1.6,
            ls="--",
            label=f"Calibrated t={t_value:.0f} d",
        )

    xi_true = float(chronicle["true_params"]["xi"])
    xi_hat = float(calibration["params_best"]["xi"])
    ax_profile.axvline(xi_true, color="tab:blue", ls=":", lw=1.4, label="xi true")
    ax_profile.axvline(xi_hat, color="tab:red", ls=":", lw=1.4, label="xi calibrated")
    ax_profile.set_xlabel("x [m]")
    ax_profile.set_ylabel("Head [m]")
    ax_profile.set_title("Head profiles h(x) at several times")
    ax_profile.grid(True, ls=":", alpha=0.45)
    ax_profile.legend(fontsize=7, ncol=2, loc="best")

    summary_lines = [
        f"method={calibration['method']}  metric={calibration['objective_metric']}",
        f"n_eval={int(result.n_evaluations)}",
    ]
    elapsed = result.metadata.get("calibration_time_seconds")
    if elapsed is not None:
        try:
            elapsed = float(elapsed)
        except (TypeError, ValueError):
            elapsed = None
    if elapsed is not None and np.isfinite(elapsed) and elapsed >= 0.0:
        summary_lines.append(f"time={elapsed:.3f} s")

    for name in calibration["parameter_names"]:
        summary_lines.append(f"{name}: true={params_true[name]:.5g} hat={params_best[name]:.5g}")
    summary_lines.append(
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}"
    )

    fig.text(
        0.5,
        0.01,
        "\n".join(summary_lines),
        ha="center",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )
    fig.suptitle("Transient 1D unconfined-aquifer calibration", fontsize=12)
    fig.tight_layout(rect=[0, 0.10, 1, 0.94])

    fig.savefig(output_png, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)
