"""Specialized forcing-resolution mixins for the Boussinesq solver."""

from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.boussinesq.forcing.dirichlet_support_resolution import (
    DirichletSupportResolutionMixin,
    ResolvedDirichletSupport,
)
from hydromodpy.solver.boussinesq.forcing.drainage_resolution import (
    DrainageResolutionMixin,
)
from hydromodpy.solver.boussinesq.forcing.initial_conditions import (
    InitialConditionResolutionMixin,
)
from hydromodpy.solver.boussinesq.forcing.recharge_resolution import (
    RechargeResolutionMixin,
)
from hydromodpy.solver.boussinesq.forcing.well_resolution import WellResolutionMixin

__all__ = [
    "DirichletSupportResolutionMixin",
    "DrainageResolutionMixin",
    "ForcingCommonMixin",
    "InitialConditionResolutionMixin",
    "RechargeResolutionMixin",
    "ResolvedDirichletSupport",
    "WellResolutionMixin",
]
