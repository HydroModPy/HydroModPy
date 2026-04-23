"""Forcing and boundary-resolution helpers for the Boussinesq solver."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hydromodpy.solver.boussinesq.forcing import (
    DirichletSupportResolutionMixin,
    DrainageResolutionMixin,
    ForcingCommonMixin,
    InitialConditionResolutionMixin,
    RechargeResolutionMixin,
    ResolvedDirichletSupport,
    WellResolutionMixin,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.spatial.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
)


@dataclass(frozen=True)
class BoussinesqForcingResolver(
    InitialConditionResolutionMixin,
    RechargeResolutionMixin,
    WellResolutionMixin,
    DirichletSupportResolutionMixin,
    DrainageResolutionMixin,
    ForcingCommonMixin,
):
    """Resolve process-level forcing payloads to Boussinesq runtime arrays."""

    mesh: BoussinesqMesh
    flow: object
    time_grid: object
    mesh_bundle: CatchmentMeshBundle | None = None
    planar_mesh_loader: Callable[[Any], object] = load_planar_mesh
    support_metadata: GmshSupportMetadata | None = None


__all__ = ["BoussinesqForcingResolver", "ResolvedDirichletSupport"]
