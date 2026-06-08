"""MF6-only helper utilities."""

from .forcing_discretization import (
    broadcast_to_stress_periods,
    discretize_spatially_distributed_source,
    has_spatially_distributed_source,
    stress_period_axes,
)
from .time_series import Ts6Series, attach_time_series, build_ts6_table

__all__ = [
    "Ts6Series",
    "attach_time_series",
    "broadcast_to_stress_periods",
    "build_ts6_table",
    "discretize_spatially_distributed_source",
    "has_spatially_distributed_source",
    "stress_period_axes",
]
