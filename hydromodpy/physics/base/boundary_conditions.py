# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Boundary-Condition Model
=================================================

Contains the shared `BoundaryCondition` Pydantic model used by process modules
that need typed boundary-condition payloads.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.base import HydroModelBase


class BoundaryCondition(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, ParamLevel("user")] = Field(..., description="id of the boundary condition (ex: h_BC, etc.)")
    value: Annotated[float, ParamLevel("user")] = Field(..., description="Value of the boundary condition")
    description: Annotated[str, ParamLevel("user")] = Field("", description="Description of the boundary condition")
    units: Annotated[str, ParamLevel("dev")] = Field("", description="Units of the boundary condition")
    type: Annotated[str, ParamLevel("user")] = Field(
        "Dirichlet",
        description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')",
    )
    data_value: Annotated[bool, ParamLevel("dev")] = Field(
        False,
        description="If True, boundary condition value is sourced from data",
    )
