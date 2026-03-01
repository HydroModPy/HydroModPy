# -*- coding: utf-8 -*-
"""
Prototype Module: Generic Sink/Source Model
==========================================

Contains the shared `SinkSource` Pydantic model used by process modules for
typed source/sink payloads.
"""

from pydantic import BaseModel, Field


class SinkSource(BaseModel):
    id: str = Field(..., description="id of the sink/source (ex: Q_well, etc.)")
    value: float = Field(..., description="Value of the sink/source")
    description: str = Field("", description="Description of the sink/source")
    units: str = Field("", description="Units of the sink/source")
    link_data: list = Field(
        default_factory=list,
        description="List of the id of the data linked to this parameter",
    )
