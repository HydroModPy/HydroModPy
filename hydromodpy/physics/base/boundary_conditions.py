"""
Prototype Module: Generic Boundary-Condition Model
=================================================

Contains the shared `BoundaryCondition` Pydantic model used by process modules
that need typed boundary-condition payloads.
"""

from typing import Annotated

from pydantic import ConfigDict, Field

from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.profile import Profile


class BoundaryCondition(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Profile.USER] = Field(
        ..., description="id of the boundary condition (ex: h_BC, etc.)"
    )
    value: Annotated[float, Profile.USER] = Field(
        ..., description="Value of the boundary condition"
    )
    description: Annotated[str, Profile.USER] = Field(
        "", description="Description of the boundary condition"
    )
    units: Annotated[str, Profile.DEV] = Field("", description="Units of the boundary condition")
    type: Annotated[str, Profile.USER] = Field(
        "Dirichlet",
        description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')",
    )
    data_value: Annotated[bool, Profile.DEV] = Field(
        False,
        description="If True, boundary condition value is sourced from data",
    )
