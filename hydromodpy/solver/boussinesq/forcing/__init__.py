"""Resolve the forcing of a flow to the arrays a Boussinesq run reads.

``BoussinesqForcingResolver`` joins one mixin per subject: the initial head,
the recharge, the wells, the Dirichlet supports, the drains, and the helpers
they share.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.boussinesq.forcing.dirichlet_support_resolution import (
    DirichletSupportResolutionMixin,
)
from hydromodpy.solver.boussinesq.forcing.drainage_resolution import DrainageResolutionMixin
from hydromodpy.solver.boussinesq.forcing.initial_conditions import (
    InitialConditionResolutionMixin,
)
from hydromodpy.solver.boussinesq.forcing.recharge_resolution import RechargeResolutionMixin
from hydromodpy.solver.boussinesq.forcing.well_resolution import WellResolutionMixin
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


__all__ = ["BoussinesqForcingResolver"]
