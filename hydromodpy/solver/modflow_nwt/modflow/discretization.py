"""Backward-compatible accessors for shared MODFLOW discretization helpers.

This legacy NWT import path is kept so existing callers and tests can keep
using ``hydromodpy.solver.modflow_nwt.modflow.discretization`` while the
implementation now lives in ``hydromodpy.solver.modflow_common``.
"""

from hydromodpy.solver.modflow_common import (
    TemporalDiscretizationResult,
    build_spatial_discretization,
    build_temporal_discretization,
    build_temporal_discretization_from_time_grid,
    project_surfaces_to_planar_grid,
    resolve_domain_surfaces,
)

__all__ = [
    "TemporalDiscretizationResult",
    "build_spatial_discretization",
    "build_temporal_discretization",
    "build_temporal_discretization_from_time_grid",
    "project_surfaces_to_planar_grid",
    "resolve_domain_surfaces",
]
