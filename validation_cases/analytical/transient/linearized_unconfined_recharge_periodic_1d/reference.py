"""Analytical reference for the 1D linearized unconfined periodic-recharge case."""

from __future__ import annotations

import numpy as np

from validation_cases.analytical.transient.common import SECONDS_PER_DAY
from validation_cases.analytical.transient.linearized_unconfined_1d import (
    LinearizedUnconfinedProperties,
    mm_day_to_m_s,
    recharge_profiles_from_period_levels,
)


def expected_linearized_unconfined_recharge_periodic_profiles(
    *,
    x: np.ndarray,
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
    angular_frequency = 2.0 * np.pi / float(period_days)
    recharge_levels_mm_day = float(mean_recharge_mm_day) + (
        float(amplitude_mm_day) * np.sin((angular_frequency * start_days) + float(phase_radians))
    )
    recharge_levels_m_per_s = np.asarray(
        [mm_day_to_m_s(value) for value in recharge_levels_mm_day],
        dtype=float,
    )
    return recharge_profiles_from_period_levels(
        x=np.asarray(x, dtype=float),
        eval_times_seconds=eval_times_seconds,
        period_start_seconds=period_start_seconds,
        recharge_levels_m_per_s=recharge_levels_m_per_s,
        base_head_m=float(base_head_m),
        properties=properties,
        n_terms=n_terms,
    )
