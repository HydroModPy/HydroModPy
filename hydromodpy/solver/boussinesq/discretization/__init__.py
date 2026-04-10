"""Explicit discretization descriptors for the Boussinesq solver."""

from hydromodpy.solver.boussinesq.discretization.space import (
    FV_TRI_CELL_CENTERED,
    SpaceSchemeSpec,
)
from hydromodpy.solver.boussinesq.discretization.time import (
    BACKWARD_EULER,
    STEADY_BALANCE,
    TimeSchemeSpec,
    resolve_time_scheme,
)

__all__ = [
    "BACKWARD_EULER",
    "FV_TRI_CELL_CENTERED",
    "STEADY_BALANCE",
    "SpaceSchemeSpec",
    "TimeSchemeSpec",
    "resolve_time_scheme",
]
