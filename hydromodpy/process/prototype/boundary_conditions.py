# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Boundary-Condition Model
=================================================

Contains the shared `BoundaryCondition` Pydantic model used by process modules
that need typed boundary-condition payloads.
"""

from pydantic import BaseModel, Field


class BoundaryCondition(BaseModel):
    id: str = Field(..., description="id of the boundary condition (ex: h_BC, etc.)")
    value: float = Field(..., description="Value of the boundary condition")
    description: str = Field("", description="Description of the boundary condition")
    units: str = Field("", description="Units of the boundary condition")
    type: str = Field(
        "Dirichlet",
        description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')",
    )
    data_value: bool = Field(
        False,
        description="If True, boundary condition value is sourced from data",
    )
