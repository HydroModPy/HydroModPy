# -*- coding: utf-8 -*-
"""
End-to-end calibration example for the linear reservoir reference case.

Workflow
--------
1. Generate a synthetic hydrological-year precipitation chronicle.
2. Convert precipitation to inflow with a simple runoff-loss rule.
3. Simulate a "true" reservoir response with known C and k.
4. Add proportional Gaussian noise to build synthetic observations.
5. Calibrate unknown C and k with generic tools from `reference_cases/`.

Run from repository root:
    python reference_cases/reservoir/example_calibration_reservoir.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sys
import tomllib

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from reference_cases.calibration_problem import Calibration
from reference_cases.objective_function import kge, nse, nse_log
from reference_cases.reservoir.reservoir_equations import ReservoirModel


DEFAULT_CONFIG_FILE = "example_calibration_reservoir.toml"


@dataclass
class ReservoirChronicleConfig:
    """Fixed settings used to generate a synthetic reservoir chronicle."""

    n_days: int
    start_year: int
    target_annual_precip_mm: float
    precip_seed: int
    runoff_coeff: float
    losses_mm_day: float
    losses_months: tuple[int, ...]
    capacity_mm_true: float
    k_per_day_true: float
    s0_mm: float
    error_fraction: float
    error_seed: int


def load_calibration_config(config_path):
    """
    Load and validate calibration configuration from TOML.
    """
    path = Path(config_path)
    with path.open("rb") as stream:
        config = tomllib.load(stream)

    for section in ("chronicle", "calibration", "bounds"):
        if section not in config:
            raise KeyError(f"Missing [{section}] section in {path}")
    return config


def generate_daily_precipitation(n_days=365, seed=42):
    """
    Generate a synthetic daily precipitation series [mm/day].
    """
    rng = np.random.default_rng(seed)
    day = np.arange(int(n_days))

    wet_probability = 0.22 + 0.20 * np.cos(2.0 * np.pi * (day - 15.0) / 365.0)
    wet_probability = np.clip(wet_probability, 0.03, 0.62)
    wet_day = rng.random(day.size) < wet_probability

    seasonal_intensity = 0.70 + 0.55 * np.cos(2.0 * np.pi * (day - 20.0) / 365.0)
    seasonal_intensity = np.clip(seasonal_intensity, 0.25, None)
    event_depth = rng.gamma(shape=1.7, scale=7.0 * seasonal_intensity, size=day.size)
    precip = wet_day.astype(float) * event_depth

    storm_weights = wet_probability / np.sum(wet_probability)
    storm_days = rng.choice(day.size, size=6, replace=False, p=storm_weights)
    precip[storm_days] += rng.uniform(20.0, 55.0, size=storm_days.size)
    return precip


def enforce_annual_precipitation_total(precip_mm_day, target_annual_mm=800.0):
    """
    Rescale precipitation to exactly match an annual target [mm/year].
    """
    precip = np.asarray(precip_mm_day, dtype=float).ravel()
    if precip.size == 0:
        raise ValueError("precip_mm_day cannot be empty")
    if target_annual_mm <= 0.0:
        raise ValueError("target_annual_mm must be > 0")

    total = float(np.sum(precip))
    if total <= 0.0:
        raise ValueError("Cannot rescale precipitation with non-positive total")
    return precip * (float(target_annual_mm) / total)


def build_hydrological_year_dates(n_days, start_year=2000):
    """
    Build daily dates for a hydrological year starting on October 1st.
    """
    start = date(int(start_year), 10, 1)
    return np.array([start + timedelta(days=i) for i in range(int(n_days))], dtype=object)


def precipitation_to_inflow(
    precip_mm_day,
    dates,
    runoff_coeff=0.15,
    losses_mm_day=1.5,
    losses_months=(4, 5, 6, 7, 8, 9),
):
    """
    Convert precipitation [mm/day] to effective precipitation and Qin [mm/day].
    """
    if not (0.0 <= float(runoff_coeff) <= 1.0):
        raise ValueError("runoff_coeff must be in [0, 1]")

    precip = np.asarray(precip_mm_day, dtype=float).ravel()
    dates = np.asarray(dates, dtype=object).ravel()
    if precip.size != dates.size:
        raise ValueError("precip_mm_day and dates must have the same length")

    losses_months = tuple(int(m) for m in losses_months)
    losses_mask = np.array([int(d.month) in losses_months for d in dates], dtype=bool)
    losses_series = np.where(losses_mask, float(losses_mm_day), 0.0)

    peff_mm_day = np.maximum(precip - losses_series, 0.0)
    qin_mm_day = peff_mm_day * float(runoff_coeff)
    return peff_mm_day, qin_mm_day


def make_piecewise_constant_daily_qin(qin_daily_mm_day):
    """
    Build Qin(t) callable from daily values (piecewise constant by day).
    """
    qin_daily = np.asarray(qin_daily_mm_day, dtype=float).ravel()
    if qin_daily.size == 0:
        raise ValueError("qin_daily_mm_day cannot be empty")

    def qin_func(t):
        day_idx = int(np.floor(float(t)))
        day_idx = int(np.clip(day_idx, 0, qin_daily.size - 1))
        return float(qin_daily[day_idx])

    return qin_func


def add_proportional_gaussian_error(
    values,
    error_fraction=0.05,
    seed=12345,
    min_sigma=1e-8,
    min_value=1e-8,
):
    """
    Add proportional Gaussian noise to a simulated chronicle.
    """
    if error_fraction < 0.0:
        raise ValueError("error_fraction must be >= 0")

    data = np.asarray(values, dtype=float).ravel()
    if data.size == 0:
        raise ValueError("values cannot be empty")

    sigma = np.maximum(float(error_fraction) * np.abs(data), float(min_sigma))
    rng = np.random.default_rng(int(seed))
    noisy = data + rng.normal(loc=0.0, scale=sigma)
    noisy = np.maximum(noisy, float(min_value))
    return noisy, sigma


def parse_chronicle_config(chronicle_cfg):
    """
    Parse chronicle section from TOML into a typed config dataclass.
    """
    return ReservoirChronicleConfig(
        n_days=int(chronicle_cfg.get("n_days", 365)),
        start_year=int(chronicle_cfg.get("start_year", 2000)),
        target_annual_precip_mm=float(chronicle_cfg.get("target_annual_precip_mm", 800.0)),
        precip_seed=int(chronicle_cfg.get("precip_seed", 42)),
        runoff_coeff=float(chronicle_cfg.get("runoff_coeff", 0.15)),
        losses_mm_day=float(chronicle_cfg.get("losses_mm_day", 1.5)),
        losses_months=tuple(chronicle_cfg.get("losses_months", (4, 5, 6, 7, 8, 9))),
        capacity_mm_true=float(chronicle_cfg["capacity_mm_true"]),
        k_per_day_true=float(chronicle_cfg["k_per_day_true"]),
        s0_mm=float(chronicle_cfg.get("s0_mm", 0.0)),
        error_fraction=float(chronicle_cfg.get("error_fraction", 0.05)),
        error_seed=int(chronicle_cfg.get("error_seed", 12345)),
    )


def build_noisy_reservoir_chronicle(chronicle_cfg):
    """
    Build all synthetic data used by the calibration exercise.

    Didactic intent
    ---------------
    This function creates the "teaching dataset" used later by calibration:
    1. create meteorological forcing (precipitation),
    2. convert it into model input Qin,
    3. simulate a noise-free "truth" with known parameters (C_true, k_true),
    4. add noise to emulate field observations.

    Returns
    -------
    dict
        Dictionary containing both forcing and target signals:
        - qout_true_mm_day : reference outflow (unknown in real life),
        - q_obs_mm_day : synthetic observed outflow (used for calibration),
        - qin_mm_day : known model forcing used by the simulator.
    """
    cfg = parse_chronicle_config(chronicle_cfg)

    # Step 1: build one hydrological-year forcing.
    dates = build_hydrological_year_dates(n_days=cfg.n_days, start_year=cfg.start_year)
    precip_raw = generate_daily_precipitation(n_days=cfg.n_days, seed=cfg.precip_seed)
    precip_mm_day = enforce_annual_precipitation_total(
        precip_mm_day=precip_raw,
        target_annual_mm=cfg.target_annual_precip_mm,
    )
    # Step 2: transform precipitation into reservoir inflow Qin.
    peff_mm_day, qin_mm_day = precipitation_to_inflow(
        precip_mm_day=precip_mm_day,
        dates=dates,
        runoff_coeff=cfg.runoff_coeff,
        losses_mm_day=cfg.losses_mm_day,
        losses_months=cfg.losses_months,
    )

    # Step 3: generate the "true" response from known (C_true, k_true).
    qin_func = make_piecewise_constant_daily_qin(qin_mm_day)
    t_eval = np.arange(cfg.n_days, dtype=float)
    model = ReservoirModel(capacity=cfg.capacity_mm_true, k=cfg.k_per_day_true)
    _, storage_true_mm, qout_true_mm_day = model.simulate(
        qin_func=qin_func,
        s0=cfg.s0_mm,
        t_span=(0.0, cfg.n_days - 1.0),
        t_eval=t_eval,
    )
    # Step 4: emulate measurement noise on outflow observations.
    q_obs_mm_day, sigma_mm_day = add_proportional_gaussian_error(
        values=qout_true_mm_day,
        error_fraction=cfg.error_fraction,
        seed=cfg.error_seed,
    )

    return {
        "config": cfg,
        "dates": dates,
        "t_days": t_eval,
        "precip_mm_day": precip_mm_day,
        "peff_mm_day": peff_mm_day,
        "qin_mm_day": qin_mm_day,
        "storage_true_mm": storage_true_mm,
        "qout_true_mm_day": qout_true_mm_day,
        "q_obs_mm_day": q_obs_mm_day,
        "sigma_mm_day": sigma_mm_day,
    }


def make_reservoir_simulator(qin_mm_day, s0_mm):
    """
    Build simulator callable compatible with generic `Calibration`.

    Why this adapter exists
    -----------------------
    `Calibration` expects a simulator with signature:
        simulator(params_dict) -> simulated_series
    while `ReservoirModel` expects explicit constructor arguments (`C`, `k`)
    and external forcing (`Qin(t)`).

    This function bridges both worlds by:
    - freezing known inputs (`qin_mm_day`, `s0_mm`),
    - exposing only unknown calibration parameters (`C`, `k`).

    Returned callable expects named parameters:
    - "C" : reservoir capacity [mm]
    - "k" : outflow coefficient [1/day]
    """
    qin = np.asarray(qin_mm_day, dtype=float).ravel()
    if qin.size == 0:
        raise ValueError("qin_mm_day cannot be empty")
    s0 = float(s0_mm)
    qin_func = make_piecewise_constant_daily_qin(qin)
    t_eval = np.arange(qin.size, dtype=float)

    def _simulate(params):
        # Values are extracted from the candidate point proposed by optimizer.
        capacity = float(params["C"])
        k_per_day = float(params["k"])
        model = ReservoirModel(capacity=capacity, k=k_per_day)
        _, _, qout = model.simulate(
            qin_func=qin_func,
            s0=s0,
            t_span=(0.0, qin.size - 1.0),
            t_eval=t_eval,
        )
        return qout

    return _simulate


def calibrate_c_k(chronicle, config):
    """
    Calibrate C and k from noisy outflow observations.

    Reading guide
    -------------
    - Observed target: `chronicle["q_obs_mm_day"]`
    - Unknowns to estimate: `C`, `k`
    - Known forcing: `chronicle["qin_mm_day"]`
    - Optimization engine: `Calibration` from `reference_cases/calibration_problem.py`

    The optimizer minimizes an internal cost `1 - score(metric)` while
    respecting parameter bounds.
    """
    calibration_cfg = config["calibration"]
    method_cfg = config.get("calibration_method", {})

    # User choices from TOML: objective score and search algorithm.
    objective_metric = str(calibration_cfg.get("objective_metric", "kge"))
    method = str(calibration_cfg.get("global_method", "simplex"))

    # Bounds define the feasible parameter space explored by optimizer.
    bounds_cfg = config["bounds"]
    bounds = {
        "C": tuple(float(v) for v in bounds_cfg["C"]),
        "k": tuple(float(v) for v in bounds_cfg["k"]),
    }

    # Build simulator(params) with forcing fixed and only C,k variable.
    simulator = make_reservoir_simulator(
        qin_mm_day=chronicle["qin_mm_day"],
        s0_mm=chronicle["config"].s0_mm,
    )
    # Create generic calibration object (metric + bounds + simulator).
    calibration_obj = Calibration(
        observed=chronicle["q_obs_mm_day"],
        simulator=simulator,
        bounds=bounds,
        objective_metric=objective_metric,
    )

    # Method-specific kwargs come from [calibration_method.<method>] in TOML.
    calibrate_kwargs = dict(method_cfg.get(method, {}))
    result = calibration_obj.calibrate(method=method, **calibrate_kwargs)

    # Convert optimizer output vector -> named parameters and simulated series.
    params_best = calibration_obj.vector_to_params(result["x_best"])
    q_calib_mm_day = calibration_obj.simulate(result["x_best"])

    # Compute a complete metric panel for interpretation/reporting.
    metrics = evaluate_metrics(
        observed=chronicle["q_obs_mm_day"],
        simulated=q_calib_mm_day,
        nse_log_floor=1e-8,
    )

    return {
        "calibration_obj": calibration_obj,
        "result": result,
        "params_best": params_best,
        "q_calib_mm_day": q_calib_mm_day,
        "metrics": metrics,
        "objective_metric": objective_metric,
        "method": method,
        "bounds": bounds,
    }


def evaluate_metrics(observed, simulated, nse_log_floor=1e-8):
    """
    Evaluate NSE, NSElog, and KGE with robust low-flow handling.

    NSElog is evaluated on clipped positive values to avoid failures when one
    of the series contains exact zeros.

    Didactic note
    -------------
    - NSE and KGE can work with zeros.
    - NSElog cannot (log(0) undefined), so we clip to a tiny positive floor.
    - This keeps the comparison stable in low-flow periods.
    """
    obs = np.asarray(observed, dtype=float).ravel()
    sim = np.asarray(simulated, dtype=float).ravel()
    if obs.shape != sim.shape:
        raise ValueError("observed and simulated must have the same shape")

    # Global fit quality in linear space.
    nse_value = float(nse(obs, sim))

    floor = float(nse_log_floor)
    if floor <= 0.0:
        raise ValueError("nse_log_floor must be > 0")
    # Low-flow-sensitive quality in log space (requires strictly positive values).
    obs_pos = np.maximum(obs, floor)
    sim_pos = np.maximum(sim, floor)
    nse_log_value = float(nse_log(obs_pos, sim_pos))

    # Balanced metric decomposed into correlation, variability, and bias.
    kge_value, components = kge(obs, sim, return_components=True)
    return {
        "NSE": nse_value,
        "NSElog": nse_log_value,
        "KGE": float(kge_value),
        "r": float(components["r"]),
        "alpha": float(components["alpha"]),
        "beta": float(components["beta"]),
    }


def select_representative_posterior_vectors(samples, n_vectors=10):
    """
    Select representative parameter vectors from posterior samples.

    Strategy
    --------
    Samples are projected onto their first principal direction and sorted.
    We then pick evenly spaced quantiles on this axis to keep diverse yet
    representative solutions.
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


def unique_rows_with_counts(samples, decimals=10):
    """
    Aggregate duplicated sample rows after rounding.

    Returns
    -------
    tuple(np.ndarray, np.ndarray)
        Unique rows and their occurrence counts.
    """
    arr = np.asarray(samples, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return np.empty((0, 0), dtype=float), np.empty(0, dtype=int)
    rounded = np.round(arr, int(decimals))
    unique_rows, counts = np.unique(rounded, axis=0, return_counts=True)
    return unique_rows, counts


def plot_calibration_result(chronicle, calibration, output_png, show_plot=True):
    """
    Plot forcing, reservoir response, and posterior diagnostics.

    For delayed-acceptance MCMC runs (`da_mh_gp`), the figure includes:
    - ~10 representative simulated hydrographs from posterior samples,
    - a parameter-distribution panel in (C, k) space.
    """
    cfg = chronicle["config"]
    dates = chronicle["dates"]
    precip = chronicle["precip_mm_day"]
    qin = chronicle["qin_mm_day"]
    q_true = chronicle["qout_true_mm_day"]
    q_obs = chronicle["q_obs_mm_day"]
    q_calib = calibration["q_calib_mm_day"]

    c_hat = float(calibration["params_best"]["C"])
    k_hat = float(calibration["params_best"]["k"])
    metrics = calibration["metrics"]
    result = calibration["result"]

    posterior_samples = np.asarray(result.get("posterior_samples", np.empty((0, 0))), dtype=float)
    chain_samples = np.asarray(result.get("samples", np.empty((0, 0))), dtype=float)
    has_posterior = posterior_samples.ndim == 2 and posterior_samples.shape[0] > 1
    posterior_unique, _ = unique_rows_with_counts(posterior_samples)
    chain_unique, _ = unique_rows_with_counts(chain_samples)
    # If posterior collapses to too few unique states, fall back to full chain
    # for visualization purposes (still based on sampled solutions).
    if posterior_unique.shape[0] >= 10:
        sample_source = posterior_samples
    elif chain_unique.shape[0] > 0:
        sample_source = chain_samples
    else:
        sample_source = posterior_samples

    if has_posterior:
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), dpi=140)
        ax0 = axes[0, 0]
        ax1 = axes[0, 1]
        ax2 = axes[1, 0]
        ax3 = axes[1, 1]
    else:
        fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=False, dpi=140)
        ax0, ax1, ax2 = axes
        ax3 = None

    ax0.bar(dates, precip, width=1.0, color="tab:blue", alpha=0.70, label="P [mm/day]")
    ax0.plot(dates, qin, color="tab:green", lw=1.5, label="Qin [mm/day]")
    ax0.set_ylabel("Forcing [mm/day]")
    ax0.grid(True, ls=":", alpha=0.40)
    ax0.legend(loc="upper right")

    ax1.plot(dates, q_true, color="tab:blue", lw=1.8, label="True Qout")
    ax1.scatter(dates, q_obs, s=13, color="tab:orange", alpha=0.70, label="Noisy observations")

    if has_posterior:
        representative = select_representative_posterior_vectors(sample_source, n_vectors=10)
        n_rep = representative.shape[0]
        # Use generic calibration simulator to map each posterior parameter vector
        # to a full discharge trajectory.
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
        # Distribution of sampled parameter values in (C, k) space.
        points, counts = unique_rows_with_counts(sample_source, decimals=10)
        ax3.scatter(
            [cfg.capacity_mm_true],
            [cfg.k_per_day_true],
            s=70,
            facecolors="none",
            edgecolors="tab:blue",
            linewidths=1.6,
            label="True",
            zorder=3,
        )
        ax3.scatter(
            [c_hat],
            [k_hat],
            s=70,
            color="tab:red",
            marker="x",
            linewidths=1.8,
            label="Best/MAP",
            zorder=3,
        )
        if points.shape[0] > 0:
            size_scale = 30.0 if counts.size == 0 else 20.0 + 120.0 * (counts / np.max(counts)) ** 0.7
            ax3.scatter(
                points[:, 0],
                points[:, 1],
                s=size_scale,
                alpha=0.70,
                color="tab:gray",
                edgecolors="white",
                linewidths=0.4,
                label="Sampled parameter states",
                zorder=4,
            )
        ax3.set_xlabel("C [mm]")
        ax3.set_ylabel("k [1/day]")
        ax3.set_title("Parameter distribution")
        ax3.grid(True, ls=":", alpha=0.40)
        ax3.legend(loc="best")

    month_locator = mdates.MonthLocator(interval=1)
    month_formatter = mdates.DateFormatter("%b")
    for axis in (ax0, ax1):
        axis.xaxis.set_major_locator(month_locator)
        axis.xaxis.set_major_formatter(month_formatter)
    if has_posterior:
        fig.autofmt_xdate()
    else:
        fig.autofmt_xdate()

    if has_posterior:
        c_q05, c_q50, c_q95 = np.quantile(posterior_samples[:, 0], [0.05, 0.50, 0.95])
        k_q05, k_q50, k_q95 = np.quantile(posterior_samples[:, 1], [0.05, 0.50, 0.95])
        posterior_txt = (
            f"Unique states: posterior={posterior_unique.shape[0]}  chain={chain_unique.shape[0]}\n"
            f"C q05/q50/q95 = {c_q05:.3f}/{c_q50:.3f}/{c_q95:.3f} mm\n"
            f"k q05/q50/q95 = {k_q05:.4f}/{k_q50:.4f}/{k_q95:.4f} 1/day"
        )
    else:
        posterior_txt = "No posterior sample distribution (deterministic method)."

    summary = (
        f"Objective={calibration['objective_metric'].upper()}  method={calibration['method']}\n"
        f"C true={cfg.capacity_mm_true:.3f} mm   C hat={c_hat:.3f} mm\n"
        f"k true={cfg.k_per_day_true:.4f} 1/day   k hat={k_hat:.4f} 1/day\n"
        f"NSE={metrics['NSE']:.4f}  NSElog={metrics['NSElog']:.4f}  KGE={metrics['KGE']:.4f}\n"
        f"{posterior_txt}"
    )
    fig.text(
        0.50,
        0.01,
        summary,
        ha="center",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )

    fig.suptitle(
        (
            "Reservoir C-k calibration on noisy hydrological chronicle\n"
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


def main():
    """
    Run the complete reservoir calibration workflow.
    """
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    config = load_calibration_config(config_path)

    chronicle = build_noisy_reservoir_chronicle(config["chronicle"])
    calibration = calibrate_c_k(chronicle, config)

    cfg = chronicle["config"]
    params_best = calibration["params_best"]
    metrics = calibration["metrics"]

    print("Calibration summary")
    print(f"  objective metric : {calibration['objective_metric']}")
    print(f"  method           : {calibration['method']}")
    print(f"  C true / hat     : {cfg.capacity_mm_true:.6f} / {params_best['C']:.6f} mm")
    print(f"  k true / hat     : {cfg.k_per_day_true:.6f} / {params_best['k']:.6f} 1/day")
    print(f"  NSE              : {metrics['NSE']:.6f}")
    print(f"  NSElog           : {metrics['NSElog']:.6f}")
    print(f"  KGE              : {metrics['KGE']:.6f}")
    print(f"  r, alpha, beta   : {metrics['r']:.6f}, {metrics['alpha']:.6f}, {metrics['beta']:.6f}")

    output_cfg = config.get("output", {})
    out_subdir = str(output_cfg.get("output_dir", "outputs"))
    show_plot = bool(output_cfg.get("show_plot", True))
    out_dir = Path(__file__).resolve().parent / out_subdir
    default_name = (
        f"reservoir_calibration_{calibration['objective_metric']}_{calibration['method']}.png"
    )
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_png = out_dir / figure_name

    plot_calibration_result(
        chronicle=chronicle,
        calibration=calibration,
        output_png=output_png,
        show_plot=show_plot,
    )
    print(f"Saved figure: {output_png}")


if __name__ == "__main__":
    main()
