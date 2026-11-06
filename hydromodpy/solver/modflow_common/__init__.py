"""Shared MODFLOW helper utilities used across solver backends.

Grid-related primitives (``SolverMesh``, ``SolverGridContext``,
spatial / temporal discretization, DIS / DISV descriptors) live in
``hydromodpy.solver.modflow_grid``; import them from there.
"""

from .binaries import (
    DEFAULT_RELEASE,
    MANIFEST_FILENAME,
    available_solvers,
    download_solver_binaries,
    ensure_platform_executable,
    ensure_solver_binary,
    ensure_solver_library,
    exe_filename,
    is_managed_cache,
    locate_solver_binary,
    read_manifest,
)
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
)

__all__ = [
    "SolverRoutingContext",
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
    "DEFAULT_RELEASE",
    "MANIFEST_FILENAME",
    "available_solvers",
    "download_solver_binaries",
    "ensure_platform_executable",
    "ensure_solver_binary",
    "ensure_solver_library",
    "exe_filename",
    "is_managed_cache",
    "locate_solver_binary",
    "read_manifest",
    "write_grid_array_to_raster",
    "build_solver_routing_context",
    "build_concentration_runtime_overrides",
    "flow_grid_shape",
]
