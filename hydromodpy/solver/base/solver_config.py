"""Top-level solver selection configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field

from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.profile import Profile
from hydromodpy.solver.base.solver_engine import SolverEngine


class SolverConfig(HydroModelBase):
    """Configuration block defining the active groundwater solver engine."""

    model_config = ConfigDict(extra="forbid")

    solver_engine: Annotated[SolverEngine, Profile.USER] = Field(
        default=SolverEngine.MODFLOW_NWT,
        description=("Groundwater solver backend ('modflownwt', 'modflow6', or 'boussinesq')."),
    )
