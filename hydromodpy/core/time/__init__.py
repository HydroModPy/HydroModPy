"""Shared simulation time-window resolution helpers."""

from hydromodpy.core.time.selection import (
    TimeSelectionError,
    grid_edges,
    period_label,
    resolve_instant,
    resolve_instants,
    resolve_period,
)
from hydromodpy.core.time.window import (
    SIMULATION_TIME_UNIT,
    ResolvedSimulationTimeGrid,
    ResolvedSimulationTimeWindow,
    ResolvedSteadySimulationTimeGrid,
    build_simulation_time_boundaries,
    has_flow_simulation_process,
    reject_invalid_step_value_spec,
    require_flow_simulation_time_grid,
    resolve_simulation_time_grid,
    resolve_simulation_time_window,
    resolve_simulation_time_window_dates,
    simulation_time_pandas_frequency,
    validate_recharge_coverage,
)

__all__ = [
    "SIMULATION_TIME_UNIT",
    "ResolvedSimulationTimeGrid",
    "ResolvedSimulationTimeWindow",
    "ResolvedSteadySimulationTimeGrid",
    "TimeSelectionError",
    "build_simulation_time_boundaries",
    "grid_edges",
    "has_flow_simulation_process",
    "period_label",
    "reject_invalid_step_value_spec",
    "require_flow_simulation_time_grid",
    "resolve_instant",
    "resolve_instants",
    "resolve_period",
    "resolve_simulation_time_grid",
    "resolve_simulation_time_window",
    "resolve_simulation_time_window_dates",
    "simulation_time_pandas_frequency",
    "validate_recharge_coverage",
]
