"""Analytical late-time reference for the transient unconfined pumping 2D case."""

from __future__ import annotations

import math

import numpy as np


SECONDS_PER_DAY = 86400.0
EULER_GAMMA = 0.5772156649015329


def _exponential_integral_e1_scalar(
    value: float, *, tol: float = 1e-12, max_terms: int = 200
) -> float:
    """Return ``E1(x)`` for one positive scalar using series/asymptotic expansions."""
    x = float(value)
    if x <= 0.0:
        raise ValueError("E1 is defined only for strictly positive values in this reference.")

    if x <= 1.0:
        factorial = 1.0
        power = -x
        series = power
        for n in range(2, max_terms + 1):
            factorial *= float(n)
            power *= -x
            delta = power / (float(n) * factorial)
            series += delta
            if abs(delta) <= tol * max(1.0, abs(series)):
                break
        return -EULER_GAMMA - math.log(x) - series

    total = 1.0
    term = 1.0
    best_total = total
    best_term_abs = abs(term)
    for n in range(1, max_terms + 1):
        term *= -float(n) / x
        candidate = total + term
        if abs(term) > best_term_abs:
            break
        total = candidate
        best_total = total
        best_term_abs = abs(term)
        if abs(term) <= tol * max(1.0, abs(total)):
            break
    return math.exp(-x) * best_total / x


def exponential_integral_e1(values) -> np.ndarray:
    """Vectorized wrapper around the positive-argument exponential integral ``E1``."""
    values_arr = np.asarray(values, dtype=float)
    out = np.empty_like(values_arr, dtype=float)
    flat_out = out.reshape(-1)
    flat_values = values_arr.reshape(-1)
    for index, value in enumerate(flat_values):
        flat_out[index] = _exponential_integral_e1_scalar(float(value))
    return out


def expected_late_time_unconfined_pumping_drawdown(
    *,
    eval_times_days,
    monitor_radii_m,
    pumping_rate_m3_day: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    specific_yield: float,
) -> np.ndarray:
    """Return late-time radial drawdown using the confined-equivalent Theis form."""
    times_days = np.asarray(eval_times_days, dtype=float).reshape(-1)
    radii_m = np.asarray(monitor_radii_m, dtype=float).reshape(-1)
    if times_days.size == 0:
        raise ValueError("eval_times_days cannot be empty")
    if radii_m.size == 0:
        raise ValueError("monitor_radii_m cannot be empty")
    if np.any(times_days <= 0.0):
        raise ValueError("eval_times_days must be strictly positive")
    if np.any(radii_m <= 0.0):
        raise ValueError("monitor_radii_m must be strictly positive")

    transmissivity_m2_day = (
        float(hydraulic_conductivity_m_per_s)
        * SECONDS_PER_DAY
        * float(reference_saturated_thickness_m)
    )
    storage = float(specific_yield)
    u = (radii_m[None, :] ** 2) * storage / (4.0 * transmissivity_m2_day * times_days[:, None])
    well_function = exponential_integral_e1(u)
    return float(pumping_rate_m3_day) * well_function / (4.0 * math.pi * transmissivity_m2_day)
