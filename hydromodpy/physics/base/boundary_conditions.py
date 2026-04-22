# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Boundary-Condition Model
=================================================

Contains the shared `BoundaryCondition` Pydantic model used by process modules
that need typed boundary-condition payloads.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.profile import Profile
from hydromodpy.core.config.base import HydroModelBase


class BoundaryCondition(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Profile.USER] = Field(..., description="id of the boundary condition (ex: h_BC, etc.)")
    value: Annotated[float, Profile.USER] = Field(..., description="Value of the boundary condition")
    description: Annotated[str, Profile.USER] = Field("", description="Description of the boundary condition")
    units: Annotated[str, Profile.DEV] = Field("", description="Units of the boundary condition")
    type: Annotated[str, Profile.USER] = Field(
        "Dirichlet",
        description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')",
    )
    data_value: Annotated[bool, Profile.DEV] = Field(
        False,
        description="If True, boundary condition value is sourced from data",
    )
