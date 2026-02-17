"""Calibration example for K and Sy on a noisy coarse-sand recession chronicle."""

from pathlib import Path
import tomllib

import matplotlib.pyplot as plt
import numpy as np

from baseflow import generate_noisy_baseflow_profile
from calibration_problem import BaseflowConfig, Calibration, make_baseflow_simulator


DEFAULT_CONFIG_FILE = "example_calibration_coarse_sand.toml"


def load_calibration_config(config_path):
    """
    Load calibration parameters from a TOML file.

    Required top-level sections:
    - `chronicle`
    - `calibration`
    - `bounds`
    """
    path = Path(config_path)
    with path.open("rb") as stream:
        config = tomllib.load(stream)

    for section in ("chronicle", "calibration", "bounds"):
        if section not in config:
            raise KeyError(f"Missing [{section}] section in {path}")
    return config


def build_noisy_coarse_sand_chronicle(profile_params):
    """
    Build synthetic coarse-sand chronicle from TOML profile parameters.

    Returns
    -------
    dict
        Contains true parameters and generated time series:
        - clean analytical recession (`q_true`)
        - noisy synthetic observations (`q_obs`)
        - per-point noise standard deviation (`sigma`)
    """
    params = dict(profile_params)
    if "error_fraction" in params:
        params["error_fraction"] = float(params["error_fraction"])
    if params.get("random_seed") is not None:
        params["random_seed"] = int(params["random_seed"])

    # Generate both truth and noisy chronicle from the same baseflow model.
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


def calibrate_k_sy(chronicle, config):
    """
    Calibrate K and Sy from noisy discharge chronicle using TOML settings.

    Optimization methods available in `optimization_methods.py`:
    - `grid_search`
    - `random_search`
    - `nelder_mead`
    - `simplex`

    Returns
    -------
    dict
        Calibration object, raw optimizer outputs, calibrated series and
        diagnostic metrics.
    """
    params = chronicle["params"]
    calibration_cfg = config["calibration"]
    optimization_cfg = config.get("optimization", {})

    objective_metric = str(calibration_cfg.get("objective_metric", "kge"))
    global_method = str(calibration_cfg.get("global_method", "random_search"))
    do_local_refine = bool(calibration_cfg.get("do_local_refine", True))

    # Bounds are read from TOML and passed as named parameters.
    bounds_cfg = config["bounds"]
    bounds = {
        "K": tuple(float(v) for v in bounds_cfg["K"]),
        "Sy": tuple(float(v) for v in bounds_cfg["Sy"]),
    }

    # Freeze fixed model settings so the simulator only depends on K and Sy.
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

    # Global exploration stage: method-specific kwargs come from [optimization.<method>].
    global_kwargs = dict(optimization_cfg.get(global_method, {}))
    result_global = calibration_obj.calibrate(
        method=global_method,
        **global_kwargs,
    )

    result_final = result_global
    # Optional local refinement stage initialized from global best point.
    if do_local_refine:
        try:
            local_cfg = dict(optimization_cfg.get("local_refine", {}))
            local_method = str(local_cfg.pop("method", "nelder_mead"))
            local_cfg.setdefault("x0", result_global["x_best"])
            result_local = calibration_obj.calibrate(
                method=local_method,
                **local_cfg,
            )
            result_final = result_local
        except Exception:
            # Keep global result if local refinement is unavailable.
            pass

    # Convert vector solution to named parameters for easier interpretation.
    best_params = calibration_obj.vector_to_params(result_final["x_best"])
    k_hat = best_params["K"]
    sy_hat = best_params["Sy"]
    q_calib = calibration_obj.simulate(result_final["x_best"])
    all_metrics = calibration_obj.evaluate_all_metrics(result_final["x_best"])

    return {
        "calibration_obj": calibration_obj,
        "bounds": bounds,
        "result_global": result_global,
        "result_final": result_final,
        "k_hat": float(k_hat),
        "sy_hat": float(sy_hat),
        "q_calib": q_calib,
        "metrics": all_metrics,
        "objective_metric": objective_metric,
        "global_method": global_method,
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
    Plot noisy observations, truth, and calibrated series + scatter diagnostic.

    The figure has two panels:
    - left: temporal evolution (log-log) to compare recession trajectories
    - right: observed vs simulated scatter with 1:1 reference
    """
    p = chronicle["params"]
    t_days = chronicle["t_days"]
    q_true = chronicle["q_true"]
    q_obs = chronicle["q_obs"]
    q_calib = calibration["q_calib"]
    k_hat = calibration["k_hat"]
    sy_hat = calibration["sy_hat"]
    metrics = calibration["metrics"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=140)
    ax_ts, ax_sc = axes

    # Left panel: time-series
    # Guard for log-scale plotting: non-positive values are masked as NaN.
    q_obs_plot = np.where(q_obs > 0.0, q_obs, np.nan)
    q_calib_plot = np.where(q_calib > 0.0, q_calib, np.nan)
    ax_ts.plot(t_days, q_true, color="tab:blue", lw=2.0, label="True analytical")
    ax_ts.scatter(t_days, q_obs_plot, s=24, color="tab:orange", alpha=0.85, label="Noisy observations")
    ax_ts.plot(t_days, q_calib_plot, color="tab:green", lw=1.8, ls="--", label="Calibrated simulation")
    ax_ts.set_xscale("log")
    ax_ts.set_yscale("log")
    ax_ts.set_xlabel("Time [days]")
    ax_ts.set_ylabel("Discharge [m^3/s]")
    ax_ts.set_title("Calibration on noisy chronicle")
    ax_ts.grid(True, which="both", ls=":", alpha=0.45)
    ax_ts.legend(loc="best")

    # Right panel: observed vs calibrated
    ax_sc.scatter(q_obs_plot, q_calib_plot, s=30, color="tab:purple", alpha=0.85, label="Pairs")
    # Build symmetric plotting range from all finite values.
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

    # Compact textual summary rendered directly in the figure.
    txt = (
        f"Objective={objective_metric.upper()}  method={global_method}\n"
        f"K true={p['K']:.2e}  K hat={k_hat:.2e}\n"
        f"Sy true={p['Sy']:.3f}  Sy hat={sy_hat:.3f}\n"
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}"
    )
    fig.text(
        0.50,
        0.05,
        txt,
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )

    fig.suptitle(
        (
            "Brutsaert K-Sy calibration from noisy coarse-sand recession\n"
            f"(error_fraction={p['error_fraction']:.0%}, n_points={p['n_points']})"
        ),
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.13, 1, 0.93])

    # Save and display for both scripted and interactive use.
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)


def main():
    """
    Run end-to-end calibration demonstration on a coarse-sand synthetic case.

    Workflow:
    1. load parameters from TOML,
    2. generate noisy observations from known K/Sy,
    3. calibrate K/Sy from noisy discharge,
    4. print diagnostics and show/save summary figure.
    """
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    config = load_calibration_config(config_path)

    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])
    calibration = calibrate_k_sy(chronicle, config)

    objective_metric = calibration["objective_metric"]
    global_method = calibration["global_method"]
    k_hat = calibration["k_hat"]
    sy_hat = calibration["sy_hat"]
    p = chronicle["params"]
    m = calibration["metrics"]

    # Console report complements the plot and is convenient in CI/log files.
    print("Calibration summary")
    print(f"  objective metric : {objective_metric}")
    print(f"  global method    : {global_method}")
    print(f"  K true / hat     : {p['K']:.6e} / {k_hat:.6e}")
    print(f"  Sy true / hat    : {p['Sy']:.6f} / {sy_hat:.6f}")
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
        chronicle,
        calibration,
        objective_metric,
        global_method,
        output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()
