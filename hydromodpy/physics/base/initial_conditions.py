# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Initial-Condition Model
================================================

Contains the shared `InitialCondition` Pydantic model used as a generic
building block by process-specific initial-condition schemas.

The base model stores the common metadata reused by process-specific initial
conditions:
- `id`: stable identifier for the variable.
- `value`: process-specific payload or scalar.
- `description`: human-readable description.
- `units`: engineering units associated with the payload.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.base import HydroModelBase


class InitialCondition(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, ParamLevel("user")] = Field(..., description="id of the initial condition (ex: h0, etc.)")
    value: Annotated[object | None, ParamLevel("user")] = Field(
        None,
        description="Process-specific initial-condition value payload.",
    )
    description: Annotated[str, ParamLevel("user")] = Field("", description="Description of the initial condition")
    units: Annotated[str, ParamLevel("user")] = Field("", description="Units of the initial condition")
