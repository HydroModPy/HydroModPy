"""Shared MODFLOW grid abstraction (mesh, discretization, descriptors).

This package hosts the grid-related primitives consumed by both the
MODFLOW 6 and MODFLOW-NWT backends. It is independent from each backend
and from ``solver/modflow_common/`` (which holds non-grid shared helpers).
"""

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
from .grid_context import SolverGridContext, grid_reference_from_solver_mesh
from .grid_mapping import (
    DiscretizationKind,
    DisDescriptor,
    DisvDescriptor,
    describe_grid,
)
from .solver_mesh import SolverMesh

__all__ = [
    "DiscretizationKind",
    "DisDescriptor",
    "DisvDescriptor",
    "SolverGridContext",
    "SolverMesh",
    "TemporalDiscretizationResult",
    "build_spatial_discretization",
    "build_temporal_discretization",
    "build_temporal_discretization_from_time_grid",
    "describe_grid",
    "grid_reference_from_solver_mesh",
    "project_surfaces_to_planar_grid",
    "resolve_domain_surfaces",
]
