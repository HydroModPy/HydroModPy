"""Analytical reference for the 1D linearized unconfined periodic-recharge case."""

from __future__ import annotations

import numpy as np

from validation_cases.analytical.transient.common import SECONDS_PER_DAY
from validation_cases.analytical.transient.linearized_unconfined_1d import (
    LinearizedUnconfinedProperties,
    mm_day_to_m_s,
    recharge_profiles_from_period_levels,
)


def periodic_recharge_levels_mm_day(
    *,
    start_days: np.ndarray,
    step_days: float,
    mean_recharge_mm_day: float,
    amplitude_mm_day: float,
    period_days: float,
    phase_radians: float = 0.0,
) -> np.ndarray:
    """Return the mean of the wave over each period, the rate the synthetic source gives it."""
    angular_frequency = 2.0 * np.pi / float(period_days)
    wave_start = (angular_frequency * np.asarray(start_days, dtype=float)) + float(phase_radians)
    wave_end = wave_start + (angular_frequency * float(step_days))
    return float(mean_recharge_mm_day) + (
        float(amplitude_mm_day)
        * (np.cos(wave_start) - np.cos(wave_end))
        / (angular_frequency * float(step_days))
    )


def expected_linearized_unconfined_recharge_periodic_profiles(
    *,
    x: np.ndarray,
    west_x: float,
    east_x: float,
    eval_times_seconds,
    period_start_seconds,
    base_head_m: float,
    mean_recharge_mm_day: float,
    amplitude_mm_day: float,
    period_days: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    specific_yield: float,
    phase_radians: float = 0.0,
    n_terms: int = 400,
) -> np.ndarray:
    """Return the transient profile matrix for a sinusoidal recharge forcing."""
    properties = LinearizedUnconfinedProperties(
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        reference_saturated_thickness_m=float(reference_saturated_thickness_m),
        specific_yield=float(specific_yield),
    )
    start_days = np.asarray(period_start_seconds, dtype=float) / SECONDS_PER_DAY
    recharge_levels_mm_day = periodic_recharge_levels_mm_day(
        start_days=start_days,
        step_days=float(np.median(np.diff(start_days))) if start_days.size > 1 else 1.0,
        mean_recharge_mm_day=mean_recharge_mm_day,
        amplitude_mm_day=amplitude_mm_day,
        period_days=period_days,
        phase_radians=phase_radians,
    )
    recharge_levels_m_per_s = np.asarray(
        [mm_day_to_m_s(value) for value in recharge_levels_mm_day],
        dtype=float,
    )
    return recharge_profiles_from_period_levels(
        x=np.asarray(x, dtype=float),
        west_x=float(west_x),
        east_x=float(east_x),
        eval_times_seconds=eval_times_seconds,
        period_start_seconds=period_start_seconds,
        recharge_levels_m_per_s=recharge_levels_m_per_s,
        base_head_m=float(base_head_m),
        properties=properties,
        n_terms=n_terms,
    )
