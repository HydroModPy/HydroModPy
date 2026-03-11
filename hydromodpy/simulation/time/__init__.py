"""Shared simulation time-window resolution and validation helpers."""

from hydromodpy.simulation.time.window import (
    ResolvedSteadySimulationTimeGrid,
    ResolvedSimulationTimeGrid,
    ResolvedSimulationTimeWindow,
    apply_explicit_time_window_to_tgrids,
    build_simulation_time_boundaries,
    has_flow_simulation_process,
    require_flow_simulation_time_grid,
    resolve_simulation_time_grid,
    resolve_simulation_time_window,
    resolve_simulation_time_window_dates,
    simulation_time_pandas_frequency,
    validate_recharge_coverage,
)

__all__ = [
    "ResolvedSteadySimulationTimeGrid",
    "ResolvedSimulationTimeGrid",
    "ResolvedSimulationTimeWindow",
    "apply_explicit_time_window_to_tgrids",
    "build_simulation_time_boundaries",
    "has_flow_simulation_process",
    "require_flow_simulation_time_grid",
    "resolve_simulation_time_grid",
    "resolve_simulation_time_window",
    "resolve_simulation_time_window_dates",
    "simulation_time_pandas_frequency",
    "validate_recharge_coverage",
]
