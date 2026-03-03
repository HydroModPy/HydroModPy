"""Top-level solver selection configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.solver.solver_engine import SolverEngine


class SolverConfig(BaseModel):
    """Configuration block defining the active groundwater solver engine."""

    model_config = ConfigDict(extra="forbid")

    solver_engine: Annotated[SolverEngine, ParamLevel("user")] = Field(
        default=SolverEngine.MODFLOW_NWT,
        description="Groundwater solver backend ('modflownwt' or 'modflow6').",
    )
