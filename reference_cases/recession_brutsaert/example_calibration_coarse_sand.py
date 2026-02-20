"""
End-to-end calibration example for a noisy Brutsaert coarse-sand recession.

Run from repository root:
    python reference_cases/recession_brutsaert/example_calibration_coarse_sand.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from reference_cases.calibration_config import (
    load_calibration_toml,
    resolve_calibration_settings,
)
from reference_cases.calibration_problem import Calibration, as_1d_array
from reference_cases.calibration_visualization import (
    build_posterior_quantile_lines,
    plot_parameter_distribution,
    select_representative_posterior_vectors,
    unique_rows_with_counts,
)
from reference_cases.recession_brutsaert.baseflow import (
    generate_noisy_baseflow_profile,
    simulate_baseflow,
)


DEFAULT_CONFIG_FILE = "example_calibration_coarse_sand.toml"
MODEL_PARAMETER_ORDER = ("K", "Sy")


@dataclass
class BaseflowConfig:
    """Fixed Brutsaert/baseflow settings used by the simulator adapter."""

    Q0: float
    solution: str = "boussinesq"
    b: float | None = None
    A: float | None = None
    L: float | None = None
    ag: float = 0.7
    p: float = 0.346


def build_noisy_coarse_sand_chronicle(profile_params):
    """Generate synthetic analytical + noisy chronicle."""
    params = dict(profile_params)
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
    Build a baseflow simulator callable compatible with generic `Calibration`.

    """
    t_seconds = as_1d_array(t_seconds, "t_seconds")

    def _simulate(params):
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
    Calibrate both parameters `K` and `Sy`.
    """
    params = chronicle["params"]
    settings = resolve_calibration_settings(
        config,
        model_parameter_order=MODEL_PARAMETER_ORDER,
        objective_default="kge",
        method_default="simplex",
        method_key="global_method",
    )
    objective_metric = settings["objective_metric"]
    global_method = settings["method"]
    bounds = settings["bounds"]
    parameter_names = settings["parameter_names"]

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

    simulator = make_baseflow_simulator(
        t_seconds=chronicle["t_seconds"],
        model_config=model_config,
    )
    calibration_obj = Calibration(
        observed=chronicle["q_obs"],
        simulator=simulator,
        bounds=bounds,
        objective_metric=objective_metric,
    )

    global_kwargs = settings["method_kwargs"]
    result_final = calibration_obj.calibrate(method=global_method, **global_kwargs)

    params_best = calibration_obj.vector_to_params(result_final["x_best"])
    params_true = {name: float(true_params_all[name]) for name in parameter_names}
    q_calib = calibration_obj.simulate(result_final["x_best"])
    all_metrics = calibration_obj.evaluate_all_metrics(result_final["x_best"])

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
    }


def _parameter_summary_lines(params_true, params_best, parameter_names):
    lines = []
    for name in parameter_names:
        if name == "K":
            lines.append(f"{name} true={params_true[name]:.2e}   {name} hat={params_best[name]:.2e}")
        else:
            lines.append(f"{name} true={params_true[name]:.4g}   {name} hat={params_best[name]:.4g}")
    return lines


def _apply_parameter_axis_scales(ax, parameter_names):
    """Keep convenient log display for K when 1D or 2D."""
    names = tuple(parameter_names)
    if len(names) == 1 and names[0] == "K":
        ax.set_xscale("log")
    if len(names) == 2:
        if names[0] == "K":
            ax.set_xscale("log")
        if names[1] == "K":
            ax.set_yscale("log")


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

    posterior_samples = np.asarray(result.get("posterior_samples", np.empty((0, 0))), dtype=float)
    chain_samples = np.asarray(result.get("samples", np.empty((0, 0))), dtype=float)
    has_posterior = posterior_samples.ndim == 2 and posterior_samples.shape[0] > 1
    posterior_unique, _ = unique_rows_with_counts(posterior_samples)
    chain_unique, _ = unique_rows_with_counts(chain_samples)

    if posterior_unique.shape[0] >= 10:
        sample_source = posterior_samples
    elif chain_unique.shape[0] > 0:
        sample_source = chain_samples
    else:
        sample_source = posterior_samples

    if has_posterior:
        fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=140)
        ax_ts, ax_sc, ax_param = axes
    else:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=140)
        ax_ts, ax_sc = axes
        ax_param = None

    q_obs_plot = np.where(q_obs > 0.0, q_obs, np.nan)
    q_calib_plot = np.where(q_calib > 0.0, q_calib, np.nan)
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
        plot_parameter_distribution(
            ax=ax_param,
            sample_source=sample_source,
            parameter_names=parameter_names,
            params_true=params_true,
            params_best=params_best,
            decimals=10,
        )
        _apply_parameter_axis_scales(ax_param, parameter_names)

    summary_lines = [
        f"Objective={objective_metric.upper()}  method={global_method}",
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
                fmt=".3g",
            )
        )
    else:
        summary_lines.append("No posterior sample distribution (deterministic method).")

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
    """Run the full TOML-driven calibration example."""
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    config = load_calibration_toml(config_path)

    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])
    calibration = calibrate_k_sy(chronicle, config)

    objective_metric = calibration["objective_metric"]
    global_method = calibration["global_method"]
    m = calibration["metrics"]

    print("Calibration summary")
    print(f"  objective metric : {objective_metric}")
    print(f"  global method    : {global_method}")
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

    output_cfg = config.get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))

    out_dir = Path(__file__).resolve().parent / out_subdir
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
