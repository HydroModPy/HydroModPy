"""Analytical reference for the 1D linearized unconfined recharge-step case."""

from __future__ import annotations

import numpy as np

from validation_cases.analytical.transient.linearized_unconfined_1d import (
    LinearizedUnconfinedProperties,
    mm_day_to_m_s,
    recharge_profiles_from_period_levels,
)


def expected_linearized_unconfined_recharge_step_profiles(
    *,
    x: np.ndarray,
    eval_times_seconds,
    period_start_seconds,
    base_head_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    specific_yield: float,
    n_terms: int = 400,
) -> np.ndarray:
    """Return the transient profile matrix for a recharge step applied at ``t=0``."""
    properties = LinearizedUnconfinedProperties(
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        reference_saturated_thickness_m=float(reference_saturated_thickness_m),
        specific_yield=float(specific_yield),
    )
    recharge_levels = np.full(
        np.asarray(period_start_seconds, dtype=float).shape,
        mm_day_to_m_s(recharge_mm_day),
        dtype=float,
    )
    return recharge_profiles_from_period_levels(
        x=np.asarray(x, dtype=float),
        eval_times_seconds=eval_times_seconds,
        period_start_seconds=period_start_seconds,
        recharge_levels_m_per_s=recharge_levels,
        base_head_m=float(base_head_m),
        properties=properties,
        n_terms=n_terms,
    )
