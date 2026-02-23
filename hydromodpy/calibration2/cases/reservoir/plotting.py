# -*- coding: utf-8 -*-
"""
Plotting helpers for reservoir calibration examples.

The plotting function is intentionally method-agnostic:
- deterministic methods: 2-panel layout,
- sampling-based methods: extra parameter-distribution panel.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.calibration2.analysis.diagnostics import build_calibration_result_view
from hydromodpy.calibration2.analysis.objective_surface import (
    build_objective_surface_approximation,
)
from hydromodpy.calibration2.analysis.plotting import (
    apply_parameter_axis_scales,
    build_calibration_performance_lines,
    build_parameter_summary_lines,
    build_posterior_summary_lines,
    plot_objective_surface,
    plot_parameter_distribution,
    select_representative_posterior_vectors,
)
from hydromodpy.calibration2.cases.reservoir.workflow import get_model_display_name


def plot_calibration_result(chronicle, calibration, output_png, show_plot=True):
    """
    Plot forcing, reservoir response and calibration diagnostics.

    Visualization keeps dedicated views for:
    - 1 parameter: histogram
    - 2 parameters: scatter cloud
    - >2 parameters: marginals boxplot

    Parameters
    ----------
    chronicle : dict
        Payload produced by `synthetic_data.build_noisy_reservoir_chronicle(...)`.
    calibration : dict
        Payload produced by reservoir calibration workflow
        (`workflow.calibrate_reservoir_model(...)`) or by the generic
        `core.case_orchestrator` through
        `cases/reservoir/case_implementation.py`.
    output_png : pathlib.Path or str
        Destination figure path.
    show_plot : bool
        If True, display figure in blocking mode.
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

    result_view = build_calibration_result_view(
        result,
        parameter_names=parameter_names,
        posterior_unique_threshold=10,
        rounding_decimals=10,
    )
    # Centralized view allows one plotting flow for all calibration methods.
    has_posterior = result_view["has_posterior"]
    sample_source = result_view["sample_source"]

    output_cfg = calibration.get("config", {}).get("output", {})
    objective_surface_requested = bool(output_cfg.get("show_objective_surface", False))
    objective_surface = None
    if objective_surface_requested:
        objective_surface = build_objective_surface_approximation(
            calibration["calibration_obj"],
            parameter_names=parameter_names,
            bounds=calibration["bounds"],
            n_evaluations=int(output_cfg.get("objective_surface_n_evaluations", 300)),
            random_seed=int(output_cfg.get("objective_surface_seed", 42)),
        )
    has_objective_surface = bool(
        objective_surface_requested
        and objective_surface is not None
        and objective_surface.get("enabled", False)
    )

    # Flexible panel layout: forcing, hydrograph, optional posterior,
    # optional objective surface.
    n_panels = 2 + int(has_posterior) + int(has_objective_surface)
    n_cols = 2
    n_rows = int(np.ceil(n_panels / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(13, 4.5 * n_rows), dpi=140)
    axes_flat = np.atleast_1d(axes).ravel()
    ax0 = axes_flat[0]
    ax1 = axes_flat[1]
    panel_idx = 2
    ax3 = axes_flat[panel_idx] if has_posterior else None
    if has_posterior:
        panel_idx += 1
    ax_obj = axes_flat[panel_idx] if has_objective_surface else None
    if has_objective_surface:
        panel_idx += 1
    for extra_ax in axes_flat[panel_idx:]:
        extra_ax.axis("off")

    # Panel 1: forcing chronicle.
    ax0.bar(dates, precip, width=1.0, color="tab:blue", alpha=0.70, label="P [mm/day]")
    if forcing_series.shape == precip.shape and not np.allclose(forcing_series, precip):
        ax0.plot(dates, forcing_series, color="tab:green", lw=1.5, label=forcing_label)
    elif forcing_label != "P [mm/day]":
        ax0.plot(dates, forcing_series, color="tab:green", lw=1.5, label=forcing_label)
    ax0.set_ylabel("Forcing [mm/day]")
    ax0.grid(True, ls=":", alpha=0.40)
    ax0.legend(loc="upper right")

    # Panel 2: hydrograph fit.
    ax1.plot(dates, q_true, color="tab:blue", lw=1.8, label="True Qout")
    ax1.scatter(dates, q_obs, s=13, color="tab:orange", alpha=0.70, label="Noisy observations")
    if has_posterior:
        representative = select_representative_posterior_vectors(sample_source, n_vectors=10)
        n_rep = representative.shape[0]
        for i, vec in enumerate(representative):
            # Plot a small subset of trajectories to visualize uncertainty.
            q_rep = calibration["calibration_obj"].simulate(vec)
            label = f"Sampled trajectories (x{n_rep})" if i == 0 else None
            ax1.plot(dates, q_rep, color="tab:red", lw=1.0, alpha=0.25, label=label)

    ax1.plot(dates, q_calib, color="tab:red", lw=1.9, ls="--", label="Best/MAP Qout")
    ax1.set_xlabel("Hydrological year (start: 1 Oct)")
    ax1.set_ylabel("Outflow [mm/day]")
    ax1.grid(True, ls=":", alpha=0.40)
    ax1.legend(loc="upper right")

    if has_posterior and ax3 is not None:
        # Panel 3 (optional): parameter uncertainty view.
        plot_parameter_distribution(
            ax=ax3,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
            decimals=10,
        )
        apply_parameter_axis_scales(
            ax=ax3,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
        )

    if has_objective_surface and ax_obj is not None:
        # Optional panel: approximated objective-cost surface from direct evaluations.
        plot_objective_surface(
            ax=ax_obj,
            objective_surface=objective_surface,
            params_true=params_true,
            params_best=params_best,
            solution_points=sample_source if has_posterior else None,
        )
        objective_domain_source = np.asarray(objective_surface["sample_points"], dtype=float)
        apply_parameter_axis_scales(
            ax=ax_obj,
            sample_source=objective_domain_source,
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

    # Bottom text block with setup, performance and diagnostics.
    summary_lines = [
        (
            f"Model={model_display}  Objective={calibration['objective_metric'].upper()}  "
            f"method={calibration['method']}"
        ),
    ]
    summary_lines.extend(
        build_calibration_performance_lines(
            result_view,
            time_fmt=".2f",
        )
    )
    summary_lines.extend(
        build_parameter_summary_lines(
            params_true=params_true,
            params_best=params_best,
            parameter_names=parameter_names,
        )
    )
    summary_lines.append(
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}"
    )

    summary_lines.extend(
        build_posterior_summary_lines(
            result_view,
            parameter_names=parameter_names,
            quantiles=(0.05, 0.50, 0.95),
            fmt=".4g",
        )
    )
    if objective_surface_requested:
        if has_objective_surface:
            log_names = tuple(objective_surface.get("log_sampling_parameter_names", ()))
            log_txt = ",".join(log_names) if log_names else "none"
            summary_lines.append(
                "Objective surface: "
                f"n_direct_sim={int(objective_surface['n_direct_evaluations'])}  "
                f"finite={int(objective_surface['n_finite_evaluations'])}  "
                f"sampling={objective_surface.get('sampling_method', 'na')}  "
                f"log_sampling={log_txt}  "
                f"interp={objective_surface['interpolation_method']}"
            )
        else:
            reason = (
                "unavailable"
                if objective_surface is None
                else str(objective_surface.get("disabled_reason", "unavailable"))
            )
            summary_lines.append(f"Objective surface: disabled ({reason})")

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
