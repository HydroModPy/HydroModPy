"""
Plotting helpers for the transient 1D groundwater calibration case.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
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


def _looks_like_calendar_axis(values) -> bool:
    values = np.asarray(values, dtype=object).ravel()
    if values.size == 0:
        return False
    sample = values[0]
    return all(hasattr(sample, attr) for attr in ("year", "month", "day"))


def _apply_time_axis_style(axes, *, use_calendar_axis: bool) -> None:
    if not use_calendar_axis:
        return
    month_locator = mdates.MonthLocator(interval=1)
    month_formatter = mdates.DateFormatter("%b")
    for ax in np.atleast_1d(axes).ravel():
        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)


def plot_forcing_chronicle(chronicle, output_png, show_plot=True):
    """
    Plot the groundwater_1d forcing chronicle only.

    Supported modes
    ---------------
    - ``hydro_step``: plot the synthetic wet/dry recharge series.
    - ``reservoir_chronicle``: plot the full chain
      precipitation -> effective rainfall -> Qin -> recharge.
    """
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    t = np.asarray(chronicle["t"], dtype=float).ravel()
    recharge_series = np.asarray(chronicle["recharge_series"], dtype=float).ravel()
    forcing_metadata = dict(chronicle.get("forcing_metadata", {}) or {})
    mode = str(forcing_metadata.get("recharge_mode", "unknown")).strip().lower()

    raw_dates = forcing_metadata.get("dates", chronicle.get("dates", ()))
    dates = np.asarray(raw_dates, dtype=object).ravel()
    if dates.size != recharge_series.size:
        dates = np.asarray(chronicle.get("dates", ()), dtype=object).ravel()
    use_calendar_axis = dates.size == recharge_series.size and _looks_like_calendar_axis(dates)

    if use_calendar_axis:
        x_values = dates
        x_label = "Hydrological year (start: 1 Oct)"
    else:
        x_values = t
        x_label = "Time [day]"

    precip_mm_day = forcing_metadata.get("precip_mm_day")
    peff_mm_day = forcing_metadata.get("peff_mm_day")
    qin_mm_day = forcing_metadata.get("qin_mm_day")
    has_reservoir_chain = (
        mode == "reservoir_chronicle"
        and precip_mm_day is not None
        and peff_mm_day is not None
        and qin_mm_day is not None
    )

    if has_reservoir_chain:
        precip_mm_day = np.asarray(precip_mm_day, dtype=float).ravel()
        peff_mm_day = np.asarray(peff_mm_day, dtype=float).ravel()
        qin_mm_day = np.asarray(qin_mm_day, dtype=float).ravel()
        fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, dpi=140)
        ax0, ax1, ax2 = axes

        ax0.bar(x_values, precip_mm_day, width=1.0, color="tab:blue", alpha=0.70, label="P [mm/day]")
        ax0.plot(x_values, peff_mm_day, color="tab:cyan", lw=1.6, label="Peff [mm/day]")
        ax0.set_ylabel("Water input [mm/day]")
        ax0.set_title("Reservoir-like forcing chain used by groundwater_1d")
        ax0.grid(True, ls=":", alpha=0.45)
        ax0.legend(loc="upper right")

        ax1.plot(x_values, qin_mm_day, color="tab:green", lw=1.8, label="Qin [mm/day]")
        ax1.set_ylabel("Inflow [mm/day]")
        ax1.grid(True, ls=":", alpha=0.45)
        ax1.legend(loc="upper right")

        ax2.plot(x_values, recharge_series, color="tab:olive", lw=1.9, label="Recharge [m/day]")
        ax2.set_xlabel(x_label)
        ax2.set_ylabel("Recharge [m/day]")
        ax2.grid(True, ls=":", alpha=0.45)
        ax2.legend(loc="upper right")

        summary_lines = [
            f"mode={mode}",
            f"annual P={float(np.sum(precip_mm_day)):.1f} mm",
            f"annual Qin={float(np.sum(qin_mm_day)):.1f} mm",
            f"annual recharge={float(np.sum(recharge_series)):.3f} m",
        ]
    else:
        fig, ax = plt.subplots(1, 1, figsize=(11, 4.5), dpi=140)
        ax.step(x_values, recharge_series, where="post", color="tab:green", lw=2.0)
        ax.set_xlabel(x_label)
        ax.set_ylabel("Recharge [m/day]")
        ax.set_title(f"Groundwater recharge forcing ({mode})")
        ax.grid(True, ls=":", alpha=0.45)
        axes = np.array([ax])

        summary_lines = [
            f"mode={mode}",
            f"n_steps={int(recharge_series.size)}",
            f"mean recharge={float(np.mean(recharge_series)):.5f} m/day",
            f"min/max recharge={float(np.min(recharge_series)):.5f}/{float(np.max(recharge_series)):.5f} m/day",
        ]

    _apply_time_axis_style(axes, use_calendar_axis=use_calendar_axis)
    if use_calendar_axis:
        fig.autofmt_xdate()

    fig.text(
        0.5,
        0.01,
        "  |  ".join(summary_lines),
        ha="center",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.30", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )
    fig.tight_layout(rect=[0, 0.06, 1, 0.98])
    fig.savefig(output_png, bbox_inches="tight")
    backend = str(plt.get_backend()).lower()
    can_show = "agg" not in backend
    if show_plot and can_show:
        plt.show()
    else:
        plt.close(fig)


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
