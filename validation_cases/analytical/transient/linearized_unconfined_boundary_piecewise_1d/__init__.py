"""Linearized transient 1D validation with a piecewise west-boundary forcing."""

from .comparison import (
    build_linearized_unconfined_boundary_piecewise_comparison,
    run_linearized_unconfined_boundary_piecewise_comparison,
)
from .plotting import plot_linearized_unconfined_boundary_piecewise_comparison
from .reference import expected_linearized_unconfined_boundary_piecewise_profiles

__all__ = [
    "build_linearized_unconfined_boundary_piecewise_comparison",
    "expected_linearized_unconfined_boundary_piecewise_profiles",
    "plot_linearized_unconfined_boundary_piecewise_comparison",
    "run_linearized_unconfined_boundary_piecewise_comparison",
]
