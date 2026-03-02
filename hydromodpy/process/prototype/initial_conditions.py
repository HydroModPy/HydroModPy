# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Initial-Condition Model
================================================

Contains the shared `InitialCondition` Pydantic model used as a generic
building block by process-specific initial-condition schemas.
"""

from pydantic import BaseModel, Field


class InitialCondition(BaseModel):
    id: str = Field(..., description="id of the initial condition (ex: h0, etc.)")
    value: object | None = Field(
        None,
        description="Process-specific initial-condition value payload.",
    )
    description: str = Field("", description="Description of the initial condition")
    units: str = Field("", description="Units of the initial condition")
