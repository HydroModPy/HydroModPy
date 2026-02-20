# -*- coding: utf-8 -*-
"""
Shared hydrological forcing utilities for reservoir reference cases.

These helpers are intentionally simple and pedagogical.

Precipitation chronicle note
----------------------------
The synthetic daily precipitation is generated in the spirit of stochastic
weather generators:
- a wet/dry occurrence process with seasonal modulation,
- event depths sampled from a Gamma law,
- a few additional heavy storm events.

This is a didactic chronicle, not a site-calibrated weather model.

References (methodological inspiration)
---------------------------------------
- Richardson, C. W. (1981). Stochastic simulation of daily precipitation,
  temperature, and solar radiation. Water Resources Research, 17(1), 182-190.
- Wilks, D. S., and Wilby, R. L. (1999). The weather generation game:
  a review of stochastic weather models. Progress in Physical Geography,
  23(3), 329-357.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np


def generate_daily_precipitation(n_days: int = 365, seed: int = 42) -> np.ndarray:
    """
    Generate a synthetic daily precipitation series [mm/day].

    The structure follows classical stochastic weather generator principles:
        1) Occurrence process (wet/dry days)
        2) Conditional amount distribution (Gamma law)
        3) Seasonal modulation of both frequency and intensity
        4) Occasional extreme storm events

    References:
    - Richardson (1981), Water Resources Research.
    - Wilks & Wilby (1999), Progress in Physical Geography.
    """

    # ------------------------------------------------------------------
    # Random generator (reproducibility)
    # ------------------------------------------------------------------
    # Uses NumPy's modern random generator.
    # Fixing the seed ensures identical synthetic series across runs.
    rng = np.random.default_rng(int(seed))

    # Time index (day of year)
    day = np.arange(int(n_days))

    # ------------------------------------------------------------------
    # 1) Occurrence model: probability of a wet day
    # ------------------------------------------------------------------
    # Seasonal cosine modulation of wet-day probability.
    # Higher probability during "wet season", lower during "dry season".
    #
    # This mimics Richardson (1981) occurrence modeling,
    # though here simplified (no Markov chain dependence).
    wet_probability = 0.22 + 0.20 * np.cos(2.0 * np.pi * (day - 15.0) / 365.0)

    # Ensure probabilities remain physically meaningful (0 ≤ p ≤ 1).
    wet_probability = np.clip(wet_probability, 0.03, 0.62)

    # Bernoulli trial: each day is wet with probability p(t).
    wet_day = rng.random(day.size) < wet_probability

    # ------------------------------------------------------------------
    # 2) Amount model: Gamma distribution for rainfall depth
    # ------------------------------------------------------------------
    # Seasonal modulation of rainfall intensity.
    # Wetter season → larger expected rainfall depth.
    seasonal_intensity = 0.70 + 0.55 * np.cos(2.0 * np.pi * (day - 20.0) / 365.0)

    # Prevent unrealistically small or negative scaling.
    seasonal_intensity = np.clip(seasonal_intensity, 0.25, None)

    # Conditional rainfall amount on wet days:
    # Gamma distribution is standard in stochastic weather generators
    # (positivity + right-skewness).
    event_depth = rng.gamma(
        shape=1.7,                       # controls skewness
        scale=7.0 * seasonal_intensity,  # seasonal mean scaling
        size=day.size
    )

    # Total precipitation: zero on dry days, Gamma on wet days.
    precip = wet_day.astype(float) * event_depth

    # ------------------------------------------------------------------
    # 3) Extreme storm enhancement
    # ------------------------------------------------------------------
    # Select a few storm days (rare but intense events).
    # Sampling is weighted by wet probability to preserve seasonality.
    storm_weights = wet_probability / np.sum(wet_probability)

    storm_days = rng.choice(
        day.size,
        size=6,              # number of extreme events
        replace=False,
        p=storm_weights
    )

    # Add heavy rainfall bursts to selected days.
    precip[storm_days] += rng.uniform(20.0, 55.0, size=storm_days.size)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    # Returns daily precipitation series [mm/day].
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

    Conceptual rule:
    Peff = max(P - losses, 0)
    Qin  = runoff_coeff * Peff

    This mirrors the "effective rainfall" idea used in conceptual rainfall-runoff
    modeling: part of rainfall is abstracted (evaporation, interception, soil
    storage deficits), the remainder contributes to runoff. Here, abstraction is
    represented by a fixed seasonal loss term for transparency in teaching.
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
