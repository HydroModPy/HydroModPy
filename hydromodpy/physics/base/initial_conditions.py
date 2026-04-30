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

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class InitialCondition(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Profile.USER] = Field(
        ..., description="id of the initial condition (ex: h0, etc.)"
    )
    value: Annotated[object | None, Profile.USER] = Field(
        None,
        description="Process-specific initial-condition value payload.",
    )
    description: Annotated[str, Profile.USER] = Field(
        "", description="Description of the initial condition"
    )
    units: Annotated[str, Profile.USER] = Field("", description="Units of the initial condition")
