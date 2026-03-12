# -*- coding: utf-8 -*-
"""
Reference-chronicle generation helpers for reservoir calibration examples.

This module prepares synthetic data used as calibration targets:
- forcing generation,
- true-model simulation,
- noise injection to create pseudo-observations.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.calibration.cases.reservoir.case_config import (
    validate_reservoir_chronicle_config,
)
from hydromodpy.calibration.cases.reservoir.workflow import MODEL_REGISTRY
from hydromodpy.hydrology.synthetic.forcing import (
    build_hydrological_year_dates,
    enforce_annual_precipitation_total,
    generate_daily_precipitation,
    make_piecewise_constant_daily_qin,
    precipitation_to_inflow,
)


@dataclass
class ReservoirChronicleConfig:
    """
    Fixed settings used to generate one synthetic reservoir chronicle.

    `true_params` and `initial_state` are model-specific and come from the
    selected model parser in `MODEL_REGISTRY`.
    """

    model_name: str
    n_days: int
    start_year: int
    target_annual_precip_mm: float
    precip_seed: int
    runoff_coeff: float
    losses_mm_day: float
    losses_months: tuple[int, ...]
    error_fraction: float
    error_seed: int
    solver_backend: str
    true_params: dict[str, float]
    initial_state: dict[str, float]


def add_proportional_gaussian_error(
    values,
    error_fraction=0.05,
    seed=12345,
    min_sigma=1e-8,
    min_value=1e-8,
):
    """
    Add proportional Gaussian noise to a simulated time series.

    Noise model:
        epsilon_i ~ N(0, sigma_i^2), sigma_i = max(error_fraction * |x_i|, min_sigma)
    """
    if error_fraction < 0.0:
        raise ValueError("error_fraction must be >= 0")

    data = np.asarray(values, dtype=float).ravel()
    if data.size == 0:
        raise ValueError("values cannot be empty")

    sigma = np.maximum(float(error_fraction) * np.abs(data), float(min_sigma))
    rng = np.random.default_rng(int(seed))
    noisy = data + rng.normal(loc=0.0, scale=sigma)
    # Keep observed flow positive for downstream log-based metrics/plots.
    noisy = np.maximum(noisy, float(min_value))
    return noisy, sigma


def parse_chronicle_config(chronicle_cfg, model_name):
    """
    Parse chronicle section from TOML into a typed config dataclass.

    This function combines:
    - case-level validation (`case_config.py`),
    - model-specific parameter extraction (`MODEL_REGISTRY` parser).
    """
    chronicle_cfg = validate_reservoir_chronicle_config(chronicle_cfg)
    model_data = MODEL_REGISTRY[model_name]
    parse_model = model_data["parse_chronicle_parameters"]
    true_params, initial_state = parse_model(chronicle_cfg)

    return ReservoirChronicleConfig(
        model_name=model_name,
        n_days=int(chronicle_cfg.get("n_days", 365)),
        start_year=int(chronicle_cfg.get("start_year", 2000)),
        target_annual_precip_mm=float(chronicle_cfg.get("target_annual_precip_mm", 800.0)),
        precip_seed=int(chronicle_cfg.get("precip_seed", 42)),
        runoff_coeff=float(chronicle_cfg.get("runoff_coeff", 0.15)),
        losses_mm_day=float(chronicle_cfg.get("losses_mm_day", 1.5)),
        losses_months=tuple(chronicle_cfg.get("losses_months", (4, 5, 6, 7, 8, 9))),
        error_fraction=float(chronicle_cfg.get("error_fraction", 0.05)),
        error_seed=int(chronicle_cfg.get("error_seed", 12345)),
        solver_backend=str(chronicle_cfg.get("solver_backend", "analytic")),
        true_params=true_params,
        initial_state=initial_state,
    )


def build_noisy_reservoir_chronicle(chronicle_cfg, model_name):
    """
    Build synthetic forcing and noisy target series used by calibration.

    Returns
    -------
    dict
        Chronicle payload consumed by reservoir workflow and plotting helpers.
    """
    # Step 1: parse and validate chronicle configuration.
    cfg = parse_chronicle_config(chronicle_cfg, model_name=model_name)
    model_data = MODEL_REGISTRY[model_name]

    # Step 2: generate forcing series over one hydrological year.
    dates = build_hydrological_year_dates(n_days=cfg.n_days, start_year=cfg.start_year)
    precip_raw = generate_daily_precipitation(n_days=cfg.n_days, seed=cfg.precip_seed)
    precip_mm_day = enforce_annual_precipitation_total(
        precip_mm_day=precip_raw,
        target_annual_mm=cfg.target_annual_precip_mm,
    )
    peff_mm_day, qin_mm_day = precipitation_to_inflow(
        precip_mm_day=precip_mm_day,
        dates=dates,
        runoff_coeff=cfg.runoff_coeff,
        losses_mm_day=cfg.losses_mm_day,
        losses_months=cfg.losses_months,
    )

    # Step 3: choose the model forcing type (`Qin` for one-reservoir, `P` for two-reservoir).
    t_eval = np.arange(cfg.n_days, dtype=float)
    forcing_kind = model_data["forcing_kind"]
    if forcing_kind == "qin":
        forcing_mm_day = qin_mm_day
    elif forcing_kind == "precip":
        forcing_mm_day = precip_mm_day
    else:
        raise ValueError(f"Unsupported forcing kind '{forcing_kind}' for model '{model_name}'")

    # Step 4: run the selected true model and collect noise-free outputs.
    forcing_func = make_piecewise_constant_daily_qin(forcing_mm_day)
    simulation = model_data["simulate_outflow"](
        params=cfg.true_params,
        initial_state=cfg.initial_state,
        forcing_func=forcing_func,
        t_span=(0.0, cfg.n_days - 1.0),
        t_eval=t_eval,
        solver_backend=cfg.solver_backend,
    )
    qout_true_mm_day = np.asarray(simulation["qout"], dtype=float)
    storage_true_mm = np.asarray(simulation["storage"], dtype=float)

    # Step 5: perturb the true outflow to obtain pseudo-observations.
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
        "forcing_mm_day": forcing_mm_day,
        "forcing_label": model_data["forcing_label"],
        "storage_true_mm": storage_true_mm,
        "qout_true_mm_day": qout_true_mm_day,
        "q_obs_mm_day": q_obs_mm_day,
        "sigma_mm_day": sigma_mm_day,
    }

