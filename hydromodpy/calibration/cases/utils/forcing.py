# -*- coding: utf-8 -*-
"""
Shared hydrological forcing utilities reusable across calibration2 cases.

This module centralizes forcing-generation logic previously specific to the
reservoir case so other cases (for example groundwater_1d) can reuse:
- synthetic precipitation chronicle generation,
- hydrological-year date support,
- rainfall-to-effective-runoff conversion,
- seasonal step forcing builders.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np


def generate_daily_precipitation(n_days: int = 365, seed: int = 42) -> np.ndarray:
    """
    Generate a synthetic daily precipitation series [mm/day].
    """
    rng = np.random.default_rng(int(seed))
    day = np.arange(int(n_days))

    wet_probability = 0.22 + 0.20 * np.cos(2.0 * np.pi * (day - 15.0) / 365.0)
    wet_probability = np.clip(wet_probability, 0.03, 0.62)
    wet_day = rng.random(day.size) < wet_probability

    seasonal_intensity = 0.70 + 0.55 * np.cos(2.0 * np.pi * (day - 20.0) / 365.0)
    seasonal_intensity = np.clip(seasonal_intensity, 0.25, None)

    event_depth = rng.gamma(
        shape=1.7,
        scale=7.0 * seasonal_intensity,
        size=day.size,
    )
    precip = wet_day.astype(float) * event_depth

    storm_weights = wet_probability / np.sum(wet_probability)
    storm_days = rng.choice(day.size, size=6, replace=False, p=storm_weights)
    precip[storm_days] += rng.uniform(20.0, 55.0, size=storm_days.size)

    return precip


def enforce_annual_precipitation_total(
    precip_mm_day: np.ndarray,
    target_annual_mm: float = 800.0,
) -> np.ndarray:
    """
    Rescale daily precipitation so cumulative annual rainfall matches target.
    """
    precip = np.asarray(precip_mm_day, dtype=float).ravel()
    if precip.size == 0:
        raise ValueError("precip_mm_day cannot be empty")
    if target_annual_mm <= 0.0:
        raise ValueError("target_annual_mm must be > 0")

    current_total = float(np.sum(precip))
    if current_total <= 0.0:
        raise ValueError("Cannot rescale precipitation with non-positive total")
    return precip * (float(target_annual_mm) / current_total)


def build_hydrological_year_dates(
    n_days: int,
    start_year: int = 2000,
) -> np.ndarray:
    """
    Build daily dates for one hydrological year starting on October 1st.
    """
    start = date(int(start_year), 10, 1)
    return np.array([start + timedelta(days=i) for i in range(int(n_days))], dtype=object)


def precipitation_to_inflow(
    precip_mm_day: np.ndarray,
    dates: np.ndarray,
    runoff_coeff: float = 0.15,
    losses_mm_day: float = 1.5,
    losses_months: tuple[int, ...] = (4, 5, 6, 7, 8, 9),
) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert precipitation [mm/day] to effective rainfall and inflow Qin [mm/day].
    """
    runoff_coeff = float(runoff_coeff)
    if not (0.0 <= runoff_coeff <= 1.0):
        raise ValueError("runoff_coeff must be in [0, 1]")

    precip = np.asarray(precip_mm_day, dtype=float).ravel()
    dates = np.asarray(dates, dtype=object).ravel()
    if precip.size != dates.size:
        raise ValueError("precip_mm_day and dates must have the same length")

    losses_months = tuple(int(month) for month in losses_months)
    losses_mask = np.array([int(d.month) in losses_months for d in dates], dtype=bool)
    losses_series = np.where(losses_mask, float(losses_mm_day), 0.0)

    peff_mm_day = np.maximum(precip - losses_series, 0.0)
    qin_mm_day = peff_mm_day * runoff_coeff
    return peff_mm_day, qin_mm_day


def build_hydrological_step_series(
    dates: np.ndarray,
    *,
    wet_months: tuple[int, ...] = (10, 11, 12, 1, 2, 3),
    wet_value: float = 0.003,
    dry_value: float = 0.0004,
) -> np.ndarray:
    """
    Build a seasonal step forcing with wet/dry hydrological periods.

    Default convention:
    - wet season: Oct-Mar
    - dry season: Apr-Sep
    """
    dates = np.asarray(dates, dtype=object).ravel()
    if dates.size == 0:
        raise ValueError("dates cannot be empty")

    wet_months = tuple(int(m) for m in wet_months)
    if any((m < 1 or m > 12) for m in wet_months):
        raise ValueError("wet_months values must be in [1, 12]")

    wet_value = float(wet_value)
    dry_value = float(dry_value)
    if wet_value < 0.0 or dry_value < 0.0:
        raise ValueError("wet_value and dry_value must be >= 0")

    wet_mask = np.array([int(d.month) in wet_months for d in dates], dtype=bool)
    return np.where(wet_mask, wet_value, dry_value).astype(float)


def build_recharge_from_reservoir_chronicle(
    *,
    n_days: int,
    start_year: int,
    target_annual_precip_mm: float,
    precip_seed: int,
    runoff_coeff: float,
    losses_mm_day: float,
    losses_months: tuple[int, ...] = (4, 5, 6, 7, 8, 9),
    scale_to_m_per_day: float = 1.0e-3,
) -> dict[str, np.ndarray]:
    """
    Build recharge using the same synthetic precipitation chronicle logic as reservoir.

    Returns
    -------
    dict
        Contains `dates`, `precip_mm_day`, `peff_mm_day`, `qin_mm_day`,
        and `recharge_m_per_day` (= `qin_mm_day * scale_to_m_per_day`).
    """
    dates = build_hydrological_year_dates(n_days=n_days, start_year=start_year)
    precip_raw = generate_daily_precipitation(n_days=n_days, seed=precip_seed)
    precip_mm_day = enforce_annual_precipitation_total(
        precip_mm_day=precip_raw,
        target_annual_mm=target_annual_precip_mm,
    )
    peff_mm_day, qin_mm_day = precipitation_to_inflow(
        precip_mm_day=precip_mm_day,
        dates=dates,
        runoff_coeff=runoff_coeff,
        losses_mm_day=losses_mm_day,
        losses_months=losses_months,
    )
    recharge_m_per_day = np.asarray(qin_mm_day, dtype=float) * float(scale_to_m_per_day)
    return {
        "dates": dates,
        "precip_mm_day": np.asarray(precip_mm_day, dtype=float),
        "peff_mm_day": np.asarray(peff_mm_day, dtype=float),
        "qin_mm_day": np.asarray(qin_mm_day, dtype=float),
        "recharge_m_per_day": recharge_m_per_day,
    }


def make_piecewise_constant_daily_qin(qin_daily_mm_day: np.ndarray):
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


__all__ = (
    "build_hydrological_year_dates",
    "build_hydrological_step_series",
    "build_recharge_from_reservoir_chronicle",
    "enforce_annual_precipitation_total",
    "generate_daily_precipitation",
    "make_piecewise_constant_daily_qin",
    "precipitation_to_inflow",
)

