"""Forcing and boundary-resolution helpers for the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["BoussinesqForcingResolver", "ResolvedDirichletSupport"]
