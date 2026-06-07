"""Analytical reference for the sloping-substratum constant-thickness case."""

from __future__ import annotations

from validation_cases.analytical.steady.boussinesq_sloping_substratum import (
    build_linear_substratum_values,
    build_linear_topography_values,
    expected_sloping_substratum_constant_thickness_profile,
    expected_sloping_substratum_constant_thickness_profile_at_x,
)

__all__ = [
    "build_linear_substratum_values",
    "build_linear_topography_values",
    "expected_sloping_substratum_constant_thickness_profile",
    "expected_sloping_substratum_constant_thickness_profile_at_x",
]
