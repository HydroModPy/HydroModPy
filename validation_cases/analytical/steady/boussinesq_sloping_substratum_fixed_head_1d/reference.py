"""Analytical reference for the sloping-substratum fixed-head case."""

from __future__ import annotations

from validation_cases.analytical.steady.boussinesq_sloping_substratum import (
    build_linear_substratum_values,
    build_linear_topography_values,
    expected_sloping_substratum_fixed_head_profile,
    expected_sloping_substratum_fixed_head_profile_at_x,
    solve_sloping_substratum_fixed_head_discharge_per_width,
)

__all__ = [
    "build_linear_substratum_values",
    "build_linear_topography_values",
    "expected_sloping_substratum_fixed_head_profile",
    "expected_sloping_substratum_fixed_head_profile_at_x",
    "solve_sloping_substratum_fixed_head_discharge_per_width",
]
