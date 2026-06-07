"""Steady 1D Boussinesq validation on a sloping substratum with constant thickness."""

from .comparison import (
    BoussinesqSlopingSubstratumConstantThicknessComparison,
    build_boussinesq_sloping_substratum_constant_thickness_comparison,
    run_boussinesq_sloping_substratum_constant_thickness_comparison,
)
from .plotting import plot_boussinesq_sloping_substratum_constant_thickness_comparison
from .reference import (
    build_linear_substratum_values,
    build_linear_topography_values,
    expected_sloping_substratum_constant_thickness_profile,
    expected_sloping_substratum_constant_thickness_profile_at_x,
)

__all__ = [
    "BoussinesqSlopingSubstratumConstantThicknessComparison",
    "build_boussinesq_sloping_substratum_constant_thickness_comparison",
    "build_linear_substratum_values",
    "build_linear_topography_values",
    "expected_sloping_substratum_constant_thickness_profile",
    "expected_sloping_substratum_constant_thickness_profile_at_x",
    "plot_boussinesq_sloping_substratum_constant_thickness_comparison",
    "run_boussinesq_sloping_substratum_constant_thickness_comparison",
]
