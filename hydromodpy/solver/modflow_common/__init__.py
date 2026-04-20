"""Shared MODFLOW helper utilities used across solver backends."""

from .binary_reader import (
    list_budget_records,
    open_cell_budget_file,
    open_head_file,
)
from .boundary_packages import (
    BoundaryCell,
    DisvBoundaryCell,
    PACKAGE_ATTRS,
    PackageKind,
    package_attr_names,
    validate_attrs,
)
from .flow_translator import (
    BoundaryKind,
    MF6_PACKAGES,
    NWT_PACKAGES,
    resolve_package,
    resolve_packages,
)
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
    broadcast_to_stress_periods,
    discretize_spatially_distributed_source,
    has_spatially_distributed_source,
    stress_period_axes,
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
    "BoundaryCell",
    "BoundaryKind",
    "DisvBoundaryCell",
    "GridReference",
    "MF6_PACKAGES",
    "NWT_PACKAGES",
    "PACKAGE_ATTRS",
    "PackageKind",
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
    "broadcast_to_stress_periods",
    "discretize_spatially_distributed_source",
    "has_spatially_distributed_source",
    "list_budget_records",
    "open_cell_budget_file",
    "open_head_file",
    "stress_period_axes",
    "Masstransfer",
    "package_attr_names",
    "resolve_package",
    "resolve_packages",
    "validate_attrs",
    "write_grid_array_to_raster",
    "build_solver_routing_context",
    "build_concentration_runtime_overrides",
    "flow_grid_shape",
    "resolve_flow_property_runtime_overrides",
]
