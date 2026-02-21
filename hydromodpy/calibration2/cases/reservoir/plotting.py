# -*- coding: utf-8 -*-
"""
Plotting helpers for reservoir calibration examples.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.calibration2.analysis.diagnostics import extract_result_samples
from hydromodpy.calibration2.analysis.plotting import (
    build_posterior_quantile_lines,
    plot_parameter_distribution,
    select_representative_posterior_vectors,
)
from hydromodpy.calibration2.cases.reservoir.workflow import get_model_display_name


def _parameter_summary_lines(params_true, params_best, parameter_names):
    lines = []
    for name in parameter_names:
        lines.append(f"{name} true={params_true[name]:.4g}   {name} hat={params_best[name]:.4g}")
    return lines


def _is_strictly_positive(values):
    arr = np.asarray(values, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    return bool(finite.size > 0 and np.all(finite > 0.0))


def _apply_parameter_axis_scales(ax, sample_source, parameter_names, params_true, params_best):
    """
    Apply log scaling on parameter panel axes when supported by data.
    """
    arr = np.asarray(sample_source, dtype=float)
    names = tuple(parameter_names)
    if arr.ndim != 2 or arr.shape[1] != len(names) or len(names) == 0:
        return

    if len(names) == 1:
        name = names[0]
        values = [arr[:, 0], [params_true.get(name, np.nan)], [params_best.get(name, np.nan)]]
        if _is_strictly_positive(np.concatenate([np.asarray(v, dtype=float).ravel() for v in values])):
            ax.set_xscale("log")
        return

    if len(names) == 2:
        x_name, y_name = names
        x_values = [arr[:, 0], [params_true.get(x_name, np.nan)], [params_best.get(x_name, np.nan)]]
        y_values = [arr[:, 1], [params_true.get(y_name, np.nan)], [params_best.get(y_name, np.nan)]]

        if _is_strictly_positive(np.concatenate([np.asarray(v, dtype=float).ravel() for v in x_values])):
            ax.set_xscale("log")
        if _is_strictly_positive(np.concatenate([np.asarray(v, dtype=float).ravel() for v in y_values])):
            ax.set_yscale("log")
        return

    if _is_strictly_positive(arr):
        ax.set_yscale("log")


def plot_calibration_result(chronicle, calibration, output_png, show_plot=True):
    """
    Plot forcing, reservoir response and calibration diagnostics.

    Visualization keeps dedicated views for:
    - 1 parameter: histogram
    - 2 parameters: scatter cloud
    - >2 parameters: marginals boxplot
    """
    cfg = chronicle["config"]
    dates = chronicle["dates"]
    precip = chronicle["precip_mm_day"]
    forcing_series = chronicle["forcing_mm_day"]
    forcing_label = chronicle["forcing_label"]
    q_true = chronicle["qout_true_mm_day"]
    q_obs = chronicle["q_obs_mm_day"]
    q_calib = calibration["q_calib_mm_day"]
    result = calibration["result"]
    metrics = calibration["metrics"]
    params_best = calibration["params_best"]
    params_true = calibration["params_true"]
    parameter_names = tuple(calibration["parameter_names"])
    model_name = calibration["model_name"]
    model_display = get_model_display_name(model_name)

    sample_views = extract_result_samples(
        result,
        n_params=len(parameter_names),
        posterior_unique_threshold=10,
        rounding_decimals=10,
    )
    posterior_samples = sample_views["posterior_samples"]
    chain_samples = sample_views["chain_samples"]
    has_posterior = sample_views["has_posterior"]
    posterior_unique = sample_views["posterior_unique"]
    chain_unique = sample_views["chain_unique"]
    sample_source = sample_views["sample_source"]

    if has_posterior:
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), dpi=140)
        ax0 = axes[0, 0]
        ax1 = axes[0, 1]
        ax2 = axes[1, 0]
        ax3 = axes[1, 1]
    else:
        fig, axes = plt.subplots(3, 1, figsize=(12, 9), dpi=140)
        ax0, ax1, ax2 = axes
        ax3 = None

    ax0.bar(dates, precip, width=1.0, color="tab:blue", alpha=0.70, label="P [mm/day]")
    if forcing_series.shape == precip.shape and not np.allclose(forcing_series, precip):
        ax0.plot(dates, forcing_series, color="tab:green", lw=1.5, label=forcing_label)
    elif forcing_label != "P [mm/day]":
        ax0.plot(dates, forcing_series, color="tab:green", lw=1.5, label=forcing_label)
    ax0.set_ylabel("Forcing [mm/day]")
    ax0.grid(True, ls=":", alpha=0.40)
    ax0.legend(loc="upper right")

    ax1.plot(dates, q_true, color="tab:blue", lw=1.8, label="True Qout")
    ax1.scatter(dates, q_obs, s=13, color="tab:orange", alpha=0.70, label="Noisy observations")
    if has_posterior:
        representative = select_representative_posterior_vectors(sample_source, n_vectors=10)
        n_rep = representative.shape[0]
        for i, vec in enumerate(representative):
            q_rep = calibration["calibration_obj"].simulate(vec)
            label = f"Sampled trajectories (x{n_rep})" if i == 0 else None
            ax1.plot(dates, q_rep, color="tab:red", lw=1.0, alpha=0.25, label=label)

    ax1.plot(dates, q_calib, color="tab:red", lw=1.9, ls="--", label="Best/MAP Qout")
    ax1.set_xlabel("Hydrological year (start: 1 Oct)")
    ax1.set_ylabel("Outflow [mm/day]")
    ax1.grid(True, ls=":", alpha=0.40)
    ax1.legend(loc="upper right")

    ax2.scatter(q_obs, q_calib, s=24, color="tab:purple", alpha=0.75, label="Pairs")
    xy_min = float(np.min(np.r_[q_obs, q_calib]))
    xy_max = float(np.max(np.r_[q_obs, q_calib]))
    ax2.plot([xy_min, xy_max], [xy_min, xy_max], color="0.25", ls="--", lw=1.2, label="1:1 line")
    span = xy_max - xy_min
    pad = 0.05 * span if span > 0.0 else 0.05 * max(abs(xy_max), 1.0)
    ax2.set_xlim(xy_min - pad, xy_max + pad)
    ax2.set_ylim(xy_min - pad, xy_max + pad)
    ax2.set_aspect("equal", adjustable="box")
    ax2.set_title("Observed vs calibrated outflow")
    ax2.set_xlabel("Observed Qout [mm/day]")
    ax2.set_ylabel("Calibrated Qout [mm/day]")
    ax2.grid(True, ls=":", alpha=0.40)
    ax2.legend(loc="upper left")

    if has_posterior and ax3 is not None:
        plot_parameter_distribution(
            ax=ax3,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
            decimals=10,
        )
        _apply_parameter_axis_scales(
            ax=ax3,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
        )

    month_locator = mdates.MonthLocator(interval=1)
    month_formatter = mdates.DateFormatter("%b")
    for axis in (ax0, ax1):
        axis.xaxis.set_major_locator(month_locator)
        axis.xaxis.set_major_formatter(month_formatter)
    fig.autofmt_xdate()

    summary_lines = [
        (
            f"Model={model_display}  Objective={calibration['objective_metric'].upper()}  "
            f"method={calibration['method']}"
        ),
    ]
    summary_lines.extend(
        _parameter_summary_lines(
            params_true=params_true,
            params_best=params_best,
            parameter_names=parameter_names,
        )
    )
    summary_lines.append(
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}"
    )

    if has_posterior:
        summary_lines.append(
            f"Unique states: posterior={posterior_unique.shape[0]}  chain={chain_unique.shape[0]}"
        )
        summary_lines.extend(
            build_posterior_quantile_lines(
                posterior_samples=posterior_samples,
                parameter_names=parameter_names,
                quantiles=(0.05, 0.50, 0.95),
                fmt=".4g",
            )
        )
    else:
        summary_lines.append("No posterior sample distribution (deterministic method).")

    fig.text(
        0.50,
        0.01,
        "\n".join(summary_lines),
        ha="center",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )

    fig.suptitle(
        (
            f"Reservoir calibration ({model_display}) on noisy hydrological chronicle\n"
            f"(annual P={float(np.sum(precip)):.1f} mm, error_fraction={cfg.error_fraction:.0%})"
        ),
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.10, 1, 0.95])

    output_path = Path(output_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)
