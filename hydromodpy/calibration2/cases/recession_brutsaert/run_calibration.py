"""
End-to-end calibration example for a noisy Brutsaert coarse-sand recession.

Run from repository root:
    python hydromodpy/calibration2/cases/recession_brutsaert/run_calibration.py

Didactic workflow
-----------------
1) Read and validate TOML configuration.
2) Build one synthetic recession chronicle:
   - analytical "true" discharge,
   - noisy observations used as calibration target.
3) Build a simulator adapter compatible with `CalibrationEngine`.
4) Calibrate the selected parameters (`K`, `Sy`) with the selected method.
5) Print scalar diagnostics and produce one summary figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.calibration2.core.engine_config import (
    load_calibration_toml,
    resolve_calibration_settings,
)
from hydromodpy.calibration2.analysis.diagnostics import (
    build_calibration_result_view,
    compute_performance_metrics,
)
from hydromodpy.calibration2.core.engine import CalibrationEngine, as_1d_array
from hydromodpy.calibration2.cases.recession_brutsaert.case_config import (
    validate_brutsaert_chronicle_config,
)
from hydromodpy.calibration2.analysis.plotting import (
    apply_parameter_axis_scales,
    build_calibration_performance_lines,
    build_parameter_summary_lines,
    build_posterior_summary_lines,
    plot_parameter_distribution,
    select_representative_posterior_vectors,
)
from hydromodpy.calibration2.cases.recession_brutsaert.model import (
    generate_noisy_baseflow_profile,
    simulate_baseflow,
)


DEFAULT_CONFIG_FILE = "config_calibration.toml"
MODEL_PARAMETER_ORDER = ("K", "Sy")


@dataclass
class BaseflowConfig:
    """
    Fixed physical settings used by the simulator adapter.

    Only `K` and `Sy` are calibrated in this example; the remaining fields are
    treated as fixed context for one calibration run.
    """

    Q0: float
    solution: str = "boussinesq"
    b: float | None = None
    A: float | None = None
    L: float | None = None
    ag: float = 0.7
    p: float = 0.346


def build_noisy_coarse_sand_chronicle(profile_params):
    """
    Generate synthetic analytical + noisy chronicle.

    The output dictionary is the common data payload used by both calibration
    and plotting steps.
    """
    params = validate_brutsaert_chronicle_config(profile_params)
    if "error_fraction" in params:
        params["error_fraction"] = float(params["error_fraction"])
    if params.get("random_seed") is not None:
        params["random_seed"] = int(params["random_seed"])

    t_s, t_days, q_true, q_obs, tc_s, sigma = generate_noisy_baseflow_profile(**params)
    return {
        "params": params,
        "t_seconds": t_s,
        "t_days": t_days,
        "q_true": q_true,
        "q_obs": q_obs,
        "sigma": sigma,
        "tc_seconds": tc_s,
    }


def _true_baseflow_parameters(chronicle_params):
    """Return model parameters used to generate the synthetic truth."""
    return {
        "K": float(chronicle_params["K"]),
        "Sy": float(chronicle_params["Sy"]),
    }


def make_baseflow_simulator(t_seconds, model_config: BaseflowConfig):
    """
    Build a baseflow simulator callable compatible with generic `CalibrationEngine`.

    Parameters
    ----------
    t_seconds : array-like
        Time grid used for all model evaluations during one calibration run.
    model_config : BaseflowConfig
        Fixed physical context (everything except calibrated parameters).

    Returns
    -------
    callable
        Function `simulate(params_dict) -> simulated_series`.

    Notes
    -----
    `CalibrationEngine` expects a simulator taking a named-parameter mapping.
    This adapter translates that generic interface to the case-specific
    `simulate_baseflow(...)` signature.
    """
    t_seconds = as_1d_array(t_seconds, "t_seconds")

    def _simulate(params):
        # Keep one uniform parameter representation for robust downstream use.
        params_all = {str(k): float(v) for k, v in params.items()}

        missing = [name for name in MODEL_PARAMETER_ORDER if name not in params_all]
        if missing:
            raise ValueError(f"Missing baseflow parameter(s): {missing}")

        return simulate_baseflow(
            t=t_seconds,
            Q0=model_config.Q0,
            K=float(params_all["K"]),
            Sy=float(params_all["Sy"]),
            solution=model_config.solution,
            b=model_config.b,
            A=model_config.A,
            L=model_config.L,
            ag=model_config.ag,
            p=model_config.p,
        )

    return _simulate


def calibrate_k_sy(chronicle, config):
    """
    Calibrate both Brutsaert parameters `K` and `Sy`.

    This function orchestrates:
    - settings resolution from TOML,
    - simulator adapter construction,
    - calibration execution,
    - post-calibration metrics on the best estimate.

    Returns
    -------
    dict
        Structured payload consumed by terminal summary and plotting.
    """
    params = chronicle["params"]
    # Resolve/validate generic calibration settings from TOML.
    settings = resolve_calibration_settings(
        config,
        model_parameter_order=MODEL_PARAMETER_ORDER,
    )
    # Generic settings resolved from TOML.
    objective_metric = settings["objective_metric"]
    global_method = settings["method"]
    parameter_set = settings["parameter_set"]
    bounds = settings["bounds"]
    parameter_names = parameter_set.names

    # Ground truth used only for diagnostics (not for optimization).
    true_params_all = _true_baseflow_parameters(params)

    model_config = BaseflowConfig(
        Q0=float(params["Q0"]),
        solution=str(params["solution"]),
        b=params.get("b"),
        A=params.get("A"),
        L=params.get("L"),
        ag=float(params.get("ag", 0.7)),
        p=float(params.get("p", 0.346)),
    )

    # Build simulator callable `params -> simulated discharge series`.
    simulator = make_baseflow_simulator(
        t_seconds=chronicle["t_seconds"],
        model_config=model_config,
    )
    calibration_obj = CalibrationEngine(
        observed=chronicle["q_obs"],
        simulator=simulator,
        parameter_set=parameter_set,
        objective_metric=objective_metric,
    )

    global_kwargs = settings["method_kwargs"]
    # Launch selected calibration method.
    result_final = calibration_obj.calibrate(method=global_method, **global_kwargs)

    # Extract best estimate in both vector and named forms.
    params_best = dict(result_final.params_best)
    params_true = {name: float(true_params_all[name]) for name in parameter_names}
    # Evaluate metrics at best parameter vector.
    q_calib = calibration_obj.simulate(result_final.x_best)
    all_metrics = compute_performance_metrics(
        observed=calibration_obj.observed,
        simulated=q_calib,
        nse_log_floor=None,
    )

    return {
        "calibration_obj": calibration_obj,
        "bounds": bounds,
        "result_final": result_final,
        "params_best": params_best,
        "params_true": params_true,
        "parameter_names": parameter_names,
        "q_calib": q_calib,
        "metrics": all_metrics,
        "objective_metric": objective_metric,
        "global_method": global_method,
        "parameter_set": parameter_set,
    }


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
    - center: observed vs simulated scatter,
    - right: parameter uncertainty view (if posterior is available).
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

    # Layout depends on whether posterior/chain samples are available.
    if has_posterior:
        fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=140)
        ax_ts, ax_sc, ax_param = axes
    else:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=140)
        ax_ts, ax_sc = axes
        ax_param = None

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

    # Panel 2: observed vs simulated cloud + 1:1 line.
    ax_sc.scatter(q_obs_plot, q_calib_plot, s=30, color="tab:purple", alpha=0.85, label="Pairs")
    finite_min = np.nanmin(np.r_[q_obs_plot, q_calib_plot])
    finite_max = np.nanmax(np.r_[q_obs_plot, q_calib_plot])
    ax_sc.plot([finite_min, finite_max], [finite_min, finite_max], color="0.25", ls="--", lw=1.2, label="1:1 line")
    ax_sc.set_xscale("log")
    ax_sc.set_yscale("log")
    ax_sc.set_xlabel("Observed (noisy) [m^3/s]")
    ax_sc.set_ylabel("Simulated (calibrated) [m^3/s]")
    ax_sc.set_title("Observed vs simulated")
    ax_sc.grid(True, which="both", ls=":", alpha=0.45)
    ax_sc.legend(loc="best")

    if has_posterior and ax_param is not None:
        # Panel 3: posterior/chain distribution in parameter space.
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
    # Step 1: load and validate configuration.
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    config = load_calibration_toml(config_path)

    # Step 2: build synthetic chronicle (truth + noise).
    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])

    # Step 3: calibrate selected parameters.
    calibration = calibrate_k_sy(chronicle, config)

    objective_metric = calibration["objective_metric"]
    global_method = calibration["global_method"]
    m = calibration["metrics"]
    result = calibration["result_final"]

    # Step 4: print compact scalar diagnostics in terminal.
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

    # Step 5: resolve output settings and produce the figure.
    output_cfg = config.get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))

    out_dir = Path(__file__).resolve().parent / out_subdir
    # Default file name encodes objective + method for easier comparison.
    default_name = f"coarse_sand_calibration_{objective_metric}_{global_method}.png"
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_png = out_dir / figure_name

    plot_calibration_result(
        chronicle=chronicle,
        calibration=calibration,
        objective_metric=objective_metric,
        global_method=global_method,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()
