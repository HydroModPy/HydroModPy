"""
End-to-end calibration example for a noisy Brutsaert coarse-sand recession.

This script demonstrates the full workflow used in this reference case:
1. load scenario and method settings from TOML,
2. generate a synthetic noisy chronicle from known parameters,
3. calibrate unknown K and Sy,
4. evaluate metrics and plot diagnostics.

Configuration file:
    `example_calibration_coarse_sand.toml`

Run from repository root:
    python reference_cases/recession_brutsaert/example_calibration_coarse_sand.py
"""

from pathlib import Path
import tomllib

import matplotlib.pyplot as plt
import numpy as np

from baseflow import generate_noisy_baseflow_profile
from calibration_problem import BaseflowConfig, Calibration, make_baseflow_simulator


DEFAULT_CONFIG_FILE = "example_calibration_coarse_sand.toml"


def load_calibration_config(config_path):
    """
    Load and validate calibration configuration from TOML.

    Parameters
    ----------
    config_path : str or pathlib.Path
        Path to a TOML file containing scenario and calibration settings.

    Returns
    -------
    dict
        Parsed TOML content.

    Required sections
    -----------------
    - `chronicle`: synthetic data-generation parameters
    - `calibration`: objective metric and method choices
    - `bounds`: parameter bounds for K and Sy

    Optional sections
    -----------------
    - `calibration_method`: method-specific hyperparameters
    - `output`: output directory, plot display, optional fixed figure name
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
    Generate synthetic analytical + noisy time series from profile parameters.

    Parameters
    ----------
    profile_params : dict
        Parameters forwarded to `generate_noisy_baseflow_profile(...)`.
        Typical keys include:
        `Q0`, `K`, `Sy`, `solution`, `A`/`L`, `ag`, `p`,
        `n_points`, `log_spacing`, `t_min_days`, `error_fraction`, `random_seed`.

    Returns
    -------
    dict
        Dictionary with:
        - `params`: normalized generation parameters
        - `t_seconds`, `t_days`: time vectors
        - `q_true`: noise-free analytical chronicle
        - `q_obs`: noisy synthetic chronicle
        - `sigma`: pointwise noise standard deviations
        - `tc_seconds`: characteristic time

    Notes
    -----
    Two fields are explicitly cast for robust reproducibility:
    - `error_fraction` -> `float`
    - `random_seed` -> `int` if provided
    """
    params = dict(profile_params)
    if "error_fraction" in params:
        params["error_fraction"] = float(params["error_fraction"])
    if params.get("random_seed") is not None:
        params["random_seed"] = int(params["random_seed"])

    # Generate both analytical and noisy series from the same model setup.
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
    Calibrate K and Sy from a noisy chronicle using TOML-driven settings.

    Parameters
    ----------
    chronicle : dict
        Output of `build_noisy_coarse_sand_chronicle(...)`.
    config : dict
        Parsed TOML content from `load_calibration_config(...)`.

    Calibration methods
    -------------------
    Methods are implemented in `calibration_method.py` and selected via TOML:
    - `grid_search`
    - `random_search`
    - `nelder_mead`
    - `simplex`

    Returns
    -------
    dict
        Dictionary containing:
        - calibration object
        - global/final method outputs
        - best parameters (`k_hat`, `sy_hat`)
        - calibrated discharge series (`q_calib`)
        - diagnostic metrics (NSE, NSElog, KGE, r, alpha, beta)
        - selected objective metric and global method names

    Workflow
    --------
    1. Read objective and method options from TOML.
    2. Build bounds and fixed model configuration.
    3. Run global calibration method.
    4. Optionally run local refinement initialized from global best point.
    5. Convert best vector solution into named parameters and evaluate metrics.
    """
    params = chronicle["params"]
    calibration_cfg = config["calibration"]
    calibration_method_cfg = config.get("calibration_method", {})

    objective_metric = str(calibration_cfg.get("objective_metric", "kge"))
    global_method = str(calibration_cfg.get("global_method", "random_search"))
    do_local_refine = bool(calibration_cfg.get("do_local_refine", True))

    # Bounds are read from TOML and converted to float tuples.
    bounds_cfg = config["bounds"]
    bounds = {
        "K": tuple(float(v) for v in bounds_cfg["K"]),
        "Sy": tuple(float(v) for v in bounds_cfg["Sy"]),
    }

    # Freeze all non-calibrated settings; only K and Sy are calibrated.
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

    # Global stage: kwargs come from [calibration_method.<global_method>].
    global_kwargs = dict(calibration_method_cfg.get(global_method, {}))
    result_global = calibration_obj.calibrate(
        method=global_method,
        **global_kwargs,
    )

    result_final = result_global

    # Optional local refinement stage from [calibration_method.local_refine].
    # We keep this block fault-tolerant so the example stays runnable even if
    # an optional method is not available in the local environment.
    if do_local_refine:
        try:
            local_cfg = dict(calibration_method_cfg.get("local_refine", {}))
            local_method = str(local_cfg.pop("method", "nelder_mead"))
            local_cfg.setdefault("x0", result_global["x_best"])
            result_local = calibration_obj.calibrate(
                method=local_method,
                **local_cfg,
            )
            result_final = result_local
        except Exception:
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
    Plot calibration diagnostics and save figure.

    Parameters
    ----------
    chronicle : dict
        Synthetic chronicle dictionary.
    calibration : dict
        Output from `calibrate_k_sy(...)`.
    objective_metric : str
        Objective metric used for the calibration run.
    global_method : str
        Global method used for the calibration run.
    output_png : str or pathlib.Path
        Destination path for the PNG figure.
    show_plot : bool
        If True, display plot interactively after saving.

    Figure layout
    -------------
    - Left panel: time-series comparison (true/noisy/calibrated)
    - Right panel: observed-vs-simulated scatter with 1:1 reference
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

    # Left panel: temporal dynamics.
    # Guard log-scale plotting by masking non-positive values.
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

    # Right panel: consistency between observations and calibrated simulation.
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

    # Figure text summary for quick interpretation.
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

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)


def main():
    """
    Run the full TOML-driven calibration example.

    Steps:
    1. Load configuration from `DEFAULT_CONFIG_FILE`.
    2. Generate synthetic chronicle from `[chronicle]`.
    3. Run calibration with `[calibration]` + `[calibration_method.*]`.
    4. Print summary and generate the diagnostic figure.
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

    # Console summary is useful for scripts/CI logs.
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
