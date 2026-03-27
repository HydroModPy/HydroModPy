"""
End-to-end calibration example for a noisy Brutsaert coarse-sand recession.

Run from repository root:
    python hydromodpy/analysis/calibration/cases/recession_brutsaert/run_calibration.py

Didactic workflow
-----------------
1) Read and validate TOML configuration.
2) Execute case implementation through generic `core.case_orchestrator`:
   - build synthetic recession chronicle,
   - build simulator adapter,
   - run calibration.
3) Print scalar diagnostics and produce one summary figure.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.analysis.calibration.core.case_orchestrator import (
    run_calibration_case_from_toml,
)
from hydromodpy.analysis.calibration.analysis.diagnostics import (
    build_calibration_result_view,
)
from hydromodpy.analysis.calibration.analysis.objective_surface import (
    build_objective_surface_approximation,
)
from hydromodpy.analysis.calibration.analysis.plotting import (
    apply_parameter_axis_scales,
    build_calibration_performance_lines,
    build_parameter_summary_lines,
    build_posterior_summary_lines,
    plot_objective_surface,
    plot_parameter_distribution,
    select_representative_posterior_vectors,
)
from hydromodpy.analysis.calibration.cases.recession_brutsaert.case_implementation import (
    CASE_IMPLEMENTATION,
)


DEFAULT_CONFIG_FILE = "config_calibration.toml"


def plot_calibration_result(
    chronicle,
    calibration,
    objective_metric,
    global_method,
    output_png,
    show_plot=True,
):
    """
    Plot calibration diagnostics and save figure.

    Visualization keeps dedicated parameter views for:
    - 1 parameter: histogram
    - 2 parameters: scatter cloud
    - >2 parameters: marginals boxplot

    The figure is split into:
    - left: time series comparison,
    - center/right: optional uncertainty and objective-surface diagnostics.
    """
    p = chronicle["params"]
    t_days = chronicle["t_days"]
    q_true = chronicle["q_true"]
    q_obs = chronicle["q_obs"]
    q_calib = calibration["q_calib"]
    params_best = calibration["params_best"]
    params_true = calibration["params_true"]
    parameter_names = tuple(calibration["parameter_names"])
    metrics = calibration["metrics"]
    result = calibration["result_final"]

    result_view = build_calibration_result_view(
        result,
        parameter_names=parameter_names,
        posterior_unique_threshold=10,
        rounding_decimals=10,
    )
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

    # Layout adapts to available diagnostics panels.
    n_panels = 1 + int(has_posterior) + int(has_objective_surface)
    fig, axes = plt.subplots(1, n_panels, figsize=(5.2 * n_panels, 5), dpi=140)
    axes = np.atleast_1d(axes).ravel()
    ax_ts = axes[0]
    panel_idx = 1
    ax_param = axes[panel_idx] if has_posterior else None
    if has_posterior:
        panel_idx += 1
    ax_obj = axes[panel_idx] if has_objective_surface else None

    # Mask non-positive values for log-scale rendering robustness.
    q_obs_plot = np.where(q_obs > 0.0, q_obs, np.nan)
    q_calib_plot = np.where(q_calib > 0.0, q_calib, np.nan)
    # Panel 1: time-domain fit quality.
    ax_ts.plot(t_days, q_true, color="tab:blue", lw=2.0, label="True analytical")
    ax_ts.scatter(t_days, q_obs_plot, s=24, color="tab:orange", alpha=0.85, label="Noisy observations")
    if has_posterior:
        representative = select_representative_posterior_vectors(sample_source, n_vectors=10)
        n_rep = representative.shape[0]
        for i, vec in enumerate(representative):
            q_rep = calibration["calibration_obj"].simulate(vec)
            q_rep_plot = np.where(q_rep > 0.0, q_rep, np.nan)
            label = f"Posterior trajectories (x{n_rep})" if i == 0 else None
            ax_ts.plot(t_days, q_rep_plot, color="tab:green", lw=1.0, alpha=0.28, label=label)

    ax_ts.plot(t_days, q_calib_plot, color="tab:green", lw=1.8, ls="--", label="Best/MAP simulation")
    ax_ts.set_xscale("log")
    ax_ts.set_yscale("log")
    ax_ts.set_xlabel("Time [days]")
    ax_ts.set_ylabel("Discharge [m^3/s]")
    ax_ts.set_title("Calibration on noisy chronicle")
    ax_ts.grid(True, which="both", ls=":", alpha=0.45)
    ax_ts.legend(loc="best")

    if has_posterior and ax_param is not None:
        # Panel 2 (optional): posterior/chain distribution in parameter space.
        plot_parameter_distribution(
            ax=ax_param,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
            decimals=10,
        )
        apply_parameter_axis_scales(
            ax=ax_param,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
            force_log_parameter_names=("K",),
            auto_log_if_positive=False,
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
            force_log_parameter_names=("K",),
            auto_log_if_positive=False,
        )

    # Bottom summary block mixes configuration, performance and posterior info.
    summary_lines = [
        f"Objective={objective_metric.upper()}  method={global_method}",
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
            format_overrides={"K": ".2e"},
        )
    )
    summary_lines.append(
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}"
    )

    # Add uncertainty diagnostics (or deterministic fallback message).
    summary_lines.extend(
        build_posterior_summary_lines(
            result_view,
            parameter_names=parameter_names,
            quantiles=(0.05, 0.50, 0.95),
            fmt=".3g",
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
        0.03,
        "\n".join(summary_lines),
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )

    fig.suptitle(
        (
            "Brutsaert calibration from noisy coarse-sand recession\n"
            f"(error_fraction={p['error_fraction']:.0%}, n_points={p['n_points']})"
        ),
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.12, 1, 0.93])

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)


def main():
    """
    Run the full TOML-driven calibration example.
    """
    # Step 1: run case calibration through the generic case orchestrator.
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    calibration = run_calibration_case_from_toml(
        config_path=config_path,
        case_implementation=CASE_IMPLEMENTATION,
    )

    objective_metric = calibration["objective_metric"]
    global_method = calibration["global_method"]
    m = calibration["metrics"]
    result = calibration["result_final"]

    # Step 2: print compact scalar diagnostics in terminal.
    print("Calibration summary")
    print(f"  objective metric : {objective_metric}")
    print(f"  global method    : {global_method}")
    print(f"  n evaluations    : {int(result.n_evaluations)}")
    elapsed_seconds = result.metadata.get("calibration_time_seconds")
    if elapsed_seconds is not None:
        try:
            elapsed_seconds = float(elapsed_seconds)
        except (TypeError, ValueError):
            elapsed_seconds = None
    if elapsed_seconds is not None and np.isfinite(elapsed_seconds) and elapsed_seconds >= 0.0:
        print(f"  calib time [s]   : {elapsed_seconds:.3f}")
    for name in calibration["parameter_names"]:
        true_value = calibration["params_true"][name]
        best_value = calibration["params_best"][name]
        if name == "K":
            print(f"  {name} true / hat     : {true_value:.6e} / {best_value:.6e}")
        else:
            print(f"  {name} true / hat     : {true_value:.6f} / {best_value:.6f}")
    print(f"  NSE              : {m['NSE']:.6f}")
    print(f"  NSElog           : {m['NSElog']:.6f}")
    print(f"  KGE              : {m['KGE']:.6f}")
    print(f"  r, alpha, beta   : {m['r']:.6f}, {m['alpha']:.6f}, {m['beta']:.6f}")

    # Step 3: resolve output settings and produce the figure.
    output_cfg = calibration["config"].get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))

    out_dir = Path(__file__).resolve().parent / out_subdir
    # Default file name encodes objective + method for easier comparison.
    default_name = f"coarse_sand_calibration_{objective_metric}_{global_method}.png"
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_png = out_dir / figure_name

    plot_calibration_result(
        chronicle=calibration["chronicle"],
        calibration=calibration,
        objective_metric=objective_metric,
        global_method=global_method,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()

