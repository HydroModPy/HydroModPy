"""Steady 1D Boussinesq validation on a sloping substratum with general fixed heads."""

from .comparison import (
    BoussinesqSlopingSubstratumFixedHeadComparison,
    build_boussinesq_sloping_substratum_fixed_head_comparison,
    run_boussinesq_sloping_substratum_fixed_head_comparison,
)
from .plotting import plot_boussinesq_sloping_substratum_fixed_head_comparison
from .reference import (
    build_linear_substratum_values,
    build_linear_topography_values,
    expected_sloping_substratum_fixed_head_profile,
    expected_sloping_substratum_fixed_head_profile_at_x,
    solve_sloping_substratum_fixed_head_discharge_per_width,
)

__all__ = [
    "BoussinesqSlopingSubstratumFixedHeadComparison",
    "build_boussinesq_sloping_substratum_fixed_head_comparison",
    "build_linear_substratum_values",
    "build_linear_topography_values",
    "expected_sloping_substratum_fixed_head_profile",
    "expected_sloping_substratum_fixed_head_profile_at_x",
    "plot_boussinesq_sloping_substratum_fixed_head_comparison",
    "run_boussinesq_sloping_substratum_fixed_head_comparison",
    "solve_sloping_substratum_fixed_head_discharge_per_width",
]
