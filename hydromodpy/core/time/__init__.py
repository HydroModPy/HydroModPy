"""Shared simulation time-window resolution and temporal-mesh helpers."""

from hydromodpy.core.time.tmesh_config import (
    TMeshConfig,
    load_tmesh_toml,
    validate_tmesh_config_data,
)
from hydromodpy.core.time.tmesh_generation import TimeGrid, TmeshGenerator
from hydromodpy.core.time.window import (
    ResolvedSimulationTimeGrid,
    ResolvedSimulationTimeWindow,
    ResolvedSteadySimulationTimeGrid,
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
    "ResolvedSimulationTimeGrid",
    "ResolvedSimulationTimeWindow",
    "ResolvedSteadySimulationTimeGrid",
    "TMeshConfig",
    "TimeGrid",
    "TmeshGenerator",
    "apply_explicit_time_window_to_tgrids",
    "build_simulation_time_boundaries",
    "has_flow_simulation_process",
    "load_tmesh_toml",
    "require_flow_simulation_time_grid",
    "resolve_simulation_time_grid",
    "resolve_simulation_time_window",
    "resolve_simulation_time_window_dates",
    "simulation_time_pandas_frequency",
    "validate_recharge_coverage",
    "validate_tmesh_config_data",
]
