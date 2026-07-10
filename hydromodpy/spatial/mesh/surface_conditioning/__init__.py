"""Solver-agnostic surface (top) conditioning kernel and drainage QC primitives.

The kernel raises a per-cell top so the mesh face graph holds no closed
depression, honouring fixed control levels (lake beds, thalwegs). It is a pure
``spatial`` function on primitives; each solver backend supplies a thin adapter
that extracts them from its native discretization and writes the top back.
"""

from __future__ import annotations

from hydromodpy.spatial.mesh.surface_conditioning.contract import (
    SurfaceConditioningInput,
    SurfaceConditioningResult,
)
from hydromodpy.spatial.mesh.surface_conditioning.fill import condition_surface_top
from hydromodpy.spatial.mesh.surface_conditioning.qc import (
    accumulation_budget,
    boundary_cells,
    classify_depressions,
    steepest_descent_accumulation,
)

__all__ = [
    "SurfaceConditioningInput",
    "SurfaceConditioningResult",
    "accumulation_budget",
    "boundary_cells",
    "classify_depressions",
    "condition_surface_top",
    "steepest_descent_accumulation",
]
