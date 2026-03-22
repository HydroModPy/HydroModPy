"""Shared MODFLOW helper utilities used across solver backends."""

from .executables import ensure_platform_executable
from .grid_context import GridReference, SolverGridContext
from .masstransfer import Masstransfer
from .raster_export import write_grid_array_to_raster
from .routing_context import SolverRoutingContext, build_solver_routing_context
from .runtime_arrays import build_concentration_runtime_overrides, flow_grid_shape
from .solver_mesh import SolverMesh

__all__ = [
    "GridReference",
    "SolverGridContext",
    "SolverMesh",
    "SolverRoutingContext",
    "ensure_platform_executable",
    "Masstransfer",
    "write_grid_array_to_raster",
    "build_solver_routing_context",
    "build_concentration_runtime_overrides",
    "flow_grid_shape",
]
