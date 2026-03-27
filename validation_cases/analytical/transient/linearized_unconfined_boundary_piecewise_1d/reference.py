"""Analytical reference for the 1D linearized unconfined boundary-piecewise case."""

from __future__ import annotations

import numpy as np

from validation_cases.analytical.transient.linearized_unconfined_1d import (
    LinearizedUnconfinedProperties,
    west_boundary_profiles_from_period_levels,
)


def expected_linearized_unconfined_boundary_piecewise_profiles(
    *,
    x: np.ndarray,
    eval_times_seconds,
    period_start_seconds,
    west_head_levels_m,
    base_head_m: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    specific_yield: float,
    n_terms: int = 400,
) -> np.ndarray:
    """Return the transient profile matrix for a piecewise west-boundary series."""
    properties = LinearizedUnconfinedProperties(
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        reference_saturated_thickness_m=float(reference_saturated_thickness_m),
        specific_yield=float(specific_yield),
    )
    return west_boundary_profiles_from_period_levels(
        x=np.asarray(x, dtype=float),
        eval_times_seconds=eval_times_seconds,
        period_start_seconds=period_start_seconds,
        west_head_levels_m=np.asarray(west_head_levels_m, dtype=float),
        base_head_m=float(base_head_m),
        properties=properties,
        n_terms=n_terms,
    )
