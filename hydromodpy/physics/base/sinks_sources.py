# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Sink/Source Model
==========================================

Contains the shared `SinkSource` Pydantic model used by process modules for
typed source/sink payloads.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.base import HydroModelBase


class SinkSource(HydroModelBase):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, ParamLevel("user")] = Field(..., description="id of the sink/source (ex: Q_well, etc.)")
    value: Annotated[float, ParamLevel("user")] = Field(..., description="Value of the sink/source")
    description: Annotated[str, ParamLevel("user")] = Field("", description="Description of the sink/source")
    units: Annotated[str, ParamLevel("dev")] = Field("", description="Units of the sink/source")
    link_data: Annotated[list, ParamLevel("dev")] = Field(
        default_factory=list,
        description="List of the id of the data linked to this parameter",
    )
