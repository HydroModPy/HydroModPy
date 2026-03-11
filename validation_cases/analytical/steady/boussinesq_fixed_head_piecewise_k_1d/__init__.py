"""Steady 1D Boussinesq validation with fixed heads and piecewise conductivity."""

from .comparison import (
    BoussinesqFixedHeadPiecewiseKComparison,
    build_boussinesq_fixed_head_piecewise_k_comparison,
    run_boussinesq_fixed_head_piecewise_k_comparison,
)
from .plotting import plot_boussinesq_fixed_head_piecewise_k_comparison
from .reference import expected_boussinesq_fixed_head_piecewise_profile

__all__ = [
    "BoussinesqFixedHeadPiecewiseKComparison",
    "build_boussinesq_fixed_head_piecewise_k_comparison",
    "expected_boussinesq_fixed_head_piecewise_profile",
    "plot_boussinesq_fixed_head_piecewise_k_comparison",
    "run_boussinesq_fixed_head_piecewise_k_comparison",
]
