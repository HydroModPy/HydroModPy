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

from dataclasses import dataclass
from pathlib import Path
import sys
import tomllib

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from reference_cases.calibration_problem import Calibration, as_1d_array
from reference_cases.recession_brutsaert.baseflow import generate_noisy_baseflow_profile, simulate_baseflow


DEFAULT_CONFIG_FILE = "example_calibration_coarse_sand.toml"


@dataclass
class BaseflowConfig:
    """
    Fixed Brutsaert/baseflow model settings used by the simulator adapter.
    """

    Q0: float
    solution: str = "boussinesq"
    b: float | None = None
    A: float | None = None
    L: float | None = None
    ag: float = 0.7
    p: float = 0.346


def make_baseflow_simulator(t_seconds, model_config: BaseflowConfig):
    """
    Build a baseflow simulator callable compatible with generic `Calibration`.

    The returned callable expects named parameters in a dict:
    - "K"
    - "Sy"
    """
    t_seconds = as_1d_array(t_seconds, "t_seconds")

    def _simulate(params):
        k_val = float(params["K"])
        sy_val = float(params["Sy"])
        return simulate_baseflow(
            t=t_seconds,
            Q0=model_config.Q0,
            K=k_val,
            Sy=sy_val,
            solution=model_config.solution,
            b=model_config.b,
            A=model_config.A,
            L=model_config.L,
            ag=model_config.ag,
            p=model_config.p,
        )

    return _simulate


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
    Methods are implemented in `reference_cases/calibration_method.py` and selected via TOML:
    - `grid_search`
    - `random_search`
    - `nelder_mead`
    - `simplex`
    - `da_mh_gp` (Delayed-Acceptance Metropolis-Hastings with GP surrogate)

    Returns
    -------
    dict
        Dictionary containing:
        - calibration object
        - calibration result
        - best parameters (`k_hat`, `sy_hat`)
        - calibrated discharge series (`q_calib`)
        - diagnostic metrics (NSE, NSElog, KGE, r, alpha, beta)
        - selected objective metric and global method names

    Workflow
    --------
    1. Read objective and method options from TOML.
    2. Build bounds and fixed model configuration.
    3. Run the selected calibration method.
    4. Convert best vector solution into named parameters and evaluate metrics.
    """
    params = chronicle["params"]
    calibration_cfg = config["calibration"]
    calibration_method_cfg = config.get("calibration_method", {})

    objective_metric = str(calibration_cfg.get("objective_metric", "kge"))
    global_method = str(calibration_cfg.get("global_method", "simplex"))

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


def select_representative_posterior_vectors(samples, n_vectors=10):
    """
    Select representative parameter vectors from posterior samples.

    Samples are projected onto their first principal direction and sampled at
    evenly spaced quantiles to keep a diverse subset of trajectories.
    """
    arr = np.asarray(samples, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return np.empty((0, 0), dtype=float)

    n_keep = int(min(max(1, n_vectors), arr.shape[0]))
    if n_keep == arr.shape[0]:
        return arr.copy()

    centered = arr - np.mean(arr, axis=0, keepdims=True)
    if np.allclose(centered, 0.0):
        indices = np.linspace(0, arr.shape[0] - 1, n_keep, dtype=int)
        return arr[indices]

    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    axis_1 = vt[0]
    scores = centered @ axis_1
    order = np.argsort(scores)
    quantile_idx = np.linspace(0, arr.shape[0] - 1, n_keep, dtype=int)
    chosen = order[quantile_idx]
    return arr[chosen]


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
    result = calibration["result_final"]

    posterior_samples = np.asarray(result.get("posterior_samples", np.empty((0, 0))), dtype=float)
    has_posterior = posterior_samples.ndim == 2 and posterior_samples.shape[0] > 1

    if has_posterior:
        fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=140)
        ax_ts, ax_sc, ax_param = axes
    else:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=140)
        ax_ts, ax_sc = axes
        ax_param = None

    # Left panel: temporal dynamics.
    # Guard log-scale plotting by masking non-positive values.
    q_obs_plot = np.where(q_obs > 0.0, q_obs, np.nan)
    q_calib_plot = np.where(q_calib > 0.0, q_calib, np.nan)
    ax_ts.plot(t_days, q_true, color="tab:blue", lw=2.0, label="True analytical")
    ax_ts.scatter(t_days, q_obs_plot, s=24, color="tab:orange", alpha=0.85, label="Noisy observations")

    if has_posterior:
        representative = select_representative_posterior_vectors(posterior_samples, n_vectors=10)
        for i, vec in enumerate(representative):
            q_rep = calibration["calibration_obj"].simulate(vec)
            q_rep_plot = np.where(q_rep > 0.0, q_rep, np.nan)
            label = "Posterior trajectories (x10)" if i == 0 else None
            ax_ts.plot(t_days, q_rep_plot, color="tab:green", lw=1.0, alpha=0.28, label=label)

    ax_ts.plot(t_days, q_calib_plot, color="tab:green", lw=1.8, ls="--", label="Best/MAP simulation")
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

    if has_posterior and ax_param is not None:
        # Posterior parameter cloud (K, Sy) with true and best/MAP markers.
        ax_param.scatter(
            posterior_samples[:, 0],
            posterior_samples[:, 1],
            s=11,
            alpha=0.25,
            color="tab:gray",
            label="Posterior samples",
        )
        ax_param.scatter([p["K"]], [p["Sy"]], s=55, color="tab:blue", label="True")
        ax_param.scatter([k_hat], [sy_hat], s=55, color="tab:green", marker="x", label="Best/MAP")
        ax_param.set_xscale("log")
        ax_param.set_xlabel("K [m/s]")
        ax_param.set_ylabel("Sy [-]")
        ax_param.set_title("Parameter distribution")
        ax_param.grid(True, which="both", ls=":", alpha=0.45)
        ax_param.legend(loc="best")

        k_q05, k_q50, k_q95 = np.quantile(posterior_samples[:, 0], [0.05, 0.50, 0.95])
        sy_q05, sy_q50, sy_q95 = np.quantile(posterior_samples[:, 1], [0.05, 0.50, 0.95])
        posterior_txt = (
            f"K q05/q50/q95={k_q05:.2e}/{k_q50:.2e}/{k_q95:.2e}\n"
            f"Sy q05/q50/q95={sy_q05:.3f}/{sy_q50:.3f}/{sy_q95:.3f}"
        )
    else:
        posterior_txt = "No posterior sample distribution (deterministic method)."

    # Figure text summary for quick interpretation.
    txt = (
        f"Objective={objective_metric.upper()}  method={global_method}\n"
        f"K true={p['K']:.2e}  K hat={k_hat:.2e}\n"
        f"Sy true={p['Sy']:.3f}  Sy hat={sy_hat:.3f}\n"
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}\n"
        f"{posterior_txt}"
    )
    fig.text(
        0.50,
        0.03,
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
