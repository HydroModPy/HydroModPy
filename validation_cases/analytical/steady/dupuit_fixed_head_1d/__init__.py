"""Dupuit fixed-head 1D validation case."""

from .comparison import (
    DupuitFixedHeadComparison,
    build_dupuit_fixed_head_comparison,
    run_dupuit_fixed_head_comparison,
)
from .plotting import plot_dupuit_fixed_head_comparison
from .reference import expected_dupuit_fixed_head_profile

__all__ = [
    "DupuitFixedHeadComparison",
    "build_dupuit_fixed_head_comparison",
    "expected_dupuit_fixed_head_profile",
    "plot_dupuit_fixed_head_comparison",
    "run_dupuit_fixed_head_comparison",
]
