"""Dupuit 1D uniform-recharge validation case."""

from .comparison import (
    DupuitUniformRechargeComparison,
    build_dupuit_uniform_recharge_comparison,
    run_dupuit_uniform_recharge_comparison,
)
from .plotting import plot_dupuit_uniform_recharge_comparison
from .reference import expected_dupuit_uniform_recharge_profile

__all__ = [
    "DupuitUniformRechargeComparison",
    "build_dupuit_uniform_recharge_comparison",
    "expected_dupuit_uniform_recharge_profile",
    "plot_dupuit_uniform_recharge_comparison",
    "run_dupuit_uniform_recharge_comparison",
]
