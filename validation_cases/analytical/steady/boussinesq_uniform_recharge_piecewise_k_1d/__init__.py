"""Steady 1D Boussinesq validation with recharge and piecewise conductivity."""

from .comparison import (
    BoussinesqUniformRechargePiecewiseKComparison,
    build_boussinesq_uniform_recharge_piecewise_k_comparison,
    run_boussinesq_uniform_recharge_piecewise_k_comparison,
)
from .plotting import plot_boussinesq_uniform_recharge_piecewise_k_comparison
from .reference import expected_boussinesq_uniform_recharge_piecewise_profile

__all__ = [
    "BoussinesqUniformRechargePiecewiseKComparison",
    "build_boussinesq_uniform_recharge_piecewise_k_comparison",
    "expected_boussinesq_uniform_recharge_piecewise_profile",
    "plot_boussinesq_uniform_recharge_piecewise_k_comparison",
    "run_boussinesq_uniform_recharge_piecewise_k_comparison",
]
