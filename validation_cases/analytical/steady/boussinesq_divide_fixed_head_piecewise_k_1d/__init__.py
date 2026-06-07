"""Steady 1D Boussinesq validation with west divide and piecewise conductivity."""

from .comparison import (
    BoussinesqDivideFixedHeadPiecewiseKComparison,
    build_boussinesq_divide_fixed_head_piecewise_k_comparison,
    run_boussinesq_divide_fixed_head_piecewise_k_comparison,
)
from .plotting import plot_boussinesq_divide_fixed_head_piecewise_k_comparison
from .reference import expected_boussinesq_divide_fixed_head_piecewise_profile

__all__ = [
    "BoussinesqDivideFixedHeadPiecewiseKComparison",
    "build_boussinesq_divide_fixed_head_piecewise_k_comparison",
    "expected_boussinesq_divide_fixed_head_piecewise_profile",
    "plot_boussinesq_divide_fixed_head_piecewise_k_comparison",
    "run_boussinesq_divide_fixed_head_piecewise_k_comparison",
]
