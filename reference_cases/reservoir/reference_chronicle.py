# -*- coding: utf-8 -*-
"""
Reference-chronicle generation helpers for reservoir calibration examples.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from reference_cases.reservoir.calibration_case import MODEL_REGISTRY
from reference_cases.reservoir.hydrological_forcing import (
    build_hydrological_year_dates,
    enforce_annual_precipitation_total,
    generate_daily_precipitation,
    make_piecewise_constant_daily_qin,
    precipitation_to_inflow,
)


@dataclass
class ReservoirChronicleConfig:
    """Fixed settings used to generate a synthetic reservoir chronicle."""

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
    true_params: dict[str, float]
    initial_state: dict[str, float]


def add_proportional_gaussian_error(
    values,
    error_fraction=0.05,
    seed=12345,
    min_sigma=1e-8,
    min_value=1e-8,
):
    """Add proportional Gaussian noise to a simulated chronicle."""
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


def parse_chronicle_config(chronicle_cfg, model_name):
    """Parse chronicle section from TOML into a typed config dataclass."""
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
        true_params=true_params,
        initial_state=initial_state,
    )


def build_noisy_reservoir_chronicle(chronicle_cfg, model_name):
    """Build synthetic forcing and target series used by calibration."""
    cfg = parse_chronicle_config(chronicle_cfg, model_name=model_name)
    model_data = MODEL_REGISTRY[model_name]

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

    t_eval = np.arange(cfg.n_days, dtype=float)
    forcing_kind = model_data["forcing_kind"]
    if forcing_kind == "qin":
        forcing_mm_day = qin_mm_day
    elif forcing_kind == "precip":
        forcing_mm_day = precip_mm_day
    else:
        raise ValueError(f"Unsupported forcing kind '{forcing_kind}' for model '{model_name}'")

    forcing_func = make_piecewise_constant_daily_qin(forcing_mm_day)
    simulation = model_data["simulate_outflow"](
        params=cfg.true_params,
        initial_state=cfg.initial_state,
        forcing_func=forcing_func,
        t_span=(0.0, cfg.n_days - 1.0),
        t_eval=t_eval,
    )
    qout_true_mm_day = np.asarray(simulation["qout"], dtype=float)
    storage_true_mm = np.asarray(simulation["storage"], dtype=float)

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
