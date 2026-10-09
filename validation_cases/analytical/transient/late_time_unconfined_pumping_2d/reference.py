"""Analytical late-time reference for the transient unconfined pumping 2D case."""

from __future__ import annotations

import math

import numpy as np

SECONDS_PER_DAY = 86400.0


def exponential_integral_e1(values) -> np.ndarray:
    """Return the exponential integral ``E1``, the Theis well function.

    SciPy evaluates it to machine precision for every positive argument. A
    hand-written series and asymptotic expansion stood here before: the
    asymptotic branch is wrong between 1 and about 8, by up to 98 per cent
    just above 1, which bent the reference beyond ``u = 1``.
    """
    from scipy.special import exp1

    values_arr = np.asarray(values, dtype=float)
    if np.any(values_arr <= 0.0):
        raise ValueError("E1 is defined only for strictly positive values in this reference.")
    return np.asarray(exp1(values_arr), dtype=float)


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
