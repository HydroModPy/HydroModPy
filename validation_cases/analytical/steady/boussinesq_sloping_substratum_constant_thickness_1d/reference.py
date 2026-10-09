"""Analytical reference for the sloping-substratum constant-thickness case.

Equal saturated thicknesses at both held heads carry the uniform flow at
constant thickness, the special branch of the fixed-head profile.
"""

from __future__ import annotations

from validation_cases.analytical.steady.boussinesq_sloping_substratum import (
    build_linear_substratum_values,
    build_linear_topography_values,
    expected_sloping_substratum_fixed_head_profile_at_x,
)

__all__ = [
    "build_linear_substratum_values",
    "build_linear_topography_values",
    "expected_sloping_substratum_fixed_head_profile_at_x",
]
