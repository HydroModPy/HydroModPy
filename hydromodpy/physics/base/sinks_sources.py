"""
Prototype Module: Generic Sink/Source Model
==========================================

Contains the shared `SinkSource` Pydantic model used by process modules for
typed source/sink payloads.
"""

from typing import Annotated

from pydantic import ConfigDict, Field

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile


class SinkSource(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Profile.USER] = Field(
        ..., description="id of the sink/source (ex: Q_well, etc.)"
    )
    value: Annotated[float, Profile.USER] = Field(..., description="Value of the sink/source")
    description: Annotated[str, Profile.USER] = Field(
        "", description="Description of the sink/source"
    )
    units: Annotated[str, Profile.DEV] = Field("", description="Units of the sink/source")
    link_data: Annotated[list, Profile.DEV] = Field(
        default_factory=list,
        description="List of the id of the data linked to this parameter",
    )
