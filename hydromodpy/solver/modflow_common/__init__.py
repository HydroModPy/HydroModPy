"""Shared MODFLOW helper utilities used across solver backends."""

from .discretization_spatial import (
    build_spatial_discretization,
    project_surfaces_to_planar_grid,
    resolve_domain_surfaces,
)
from .discretization_temporal import (
    TemporalDiscretizationResult,
    build_temporal_discretization,
    build_temporal_discretization_from_time_grid,
)
from .executables import ensure_platform_executable
from .forcing_discretization import (
    discretize_spatially_distributed_source,
    has_spatially_distributed_source,
)
from .grid_context import GridReference, SolverGridContext
from .masstransfer import Masstransfer
from .options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from .raster_export import write_grid_array_to_raster
from .routing_context import SolverRoutingContext, build_solver_routing_context
from .runtime_arrays import (
    build_concentration_runtime_overrides,
    flow_grid_shape,
    resolve_flow_property_runtime_overrides,
)
from .solver_mesh import SolverMesh

__all__ = [
    "GridReference",
    "SolverGridContext",
    "SolverMesh",
    "SolverRoutingContext",
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
    "TemporalDiscretizationResult",
    "build_spatial_discretization",
    "resolve_domain_surfaces",
    "project_surfaces_to_planar_grid",
    "build_temporal_discretization",
    "build_temporal_discretization_from_time_grid",
    "ensure_platform_executable",
    "discretize_spatially_distributed_source",
    "has_spatially_distributed_source",
    "Masstransfer",
    "write_grid_array_to_raster",
    "build_solver_routing_context",
    "build_concentration_runtime_overrides",
    "flow_grid_shape",
    "resolve_flow_property_runtime_overrides",
]
