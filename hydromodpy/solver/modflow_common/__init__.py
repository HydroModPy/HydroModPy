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
    ensure_solver_binary,
    exe_filename,
    is_managed_cache,
    locate_solver_binary,
    read_manifest,
)
from .boundary_packages import (
    PACKAGE_ATTRS,
    BoundaryCell,
    DisvBoundaryCell,
    PackageKind,
    package_attr_names,
    validate_attrs,
)
from .executables import ensure_platform_executable
from .flow_translator import (
    MF6_PACKAGES,
    NWT_PACKAGES,
    BoundaryKind,
    resolve_package,
    resolve_packages,
)
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

__all__ = [
    "BoundaryCell",
    "BoundaryKind",
    "DisvBoundaryCell",
    "MF6_PACKAGES",
    "NWT_PACKAGES",
    "PACKAGE_ATTRS",
    "PackageKind",
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
    "exe_filename",
    "is_managed_cache",
    "locate_solver_binary",
    "read_manifest",
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
