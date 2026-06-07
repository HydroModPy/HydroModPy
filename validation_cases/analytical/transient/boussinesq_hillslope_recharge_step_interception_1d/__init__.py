"""Transient Boussinesq hillslope recharge-step interception benchmark."""

from .comparison import (
    BoussinesqTransientHillslopeInterceptionComparison,
    build_boussinesq_hillslope_recharge_step_interception_comparison,
    run_boussinesq_hillslope_recharge_step_interception_comparison,
)
from .plotting import plot_boussinesq_hillslope_recharge_step_interception_comparison
from .reference import (
    build_hillslope_topography_values,
    build_interception_trajectory_from_profiles,
    expected_linearized_hillslope_recharge_step_profiles,
    first_inland_interception_time_seconds,
)

__all__ = [
    "BoussinesqTransientHillslopeInterceptionComparison",
    "build_boussinesq_hillslope_recharge_step_interception_comparison",
    "build_hillslope_topography_values",
    "build_interception_trajectory_from_profiles",
    "expected_linearized_hillslope_recharge_step_profiles",
    "first_inland_interception_time_seconds",
    "plot_boussinesq_hillslope_recharge_step_interception_comparison",
    "run_boussinesq_hillslope_recharge_step_interception_comparison",
]
