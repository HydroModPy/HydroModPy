"""Pydantic schema for intermittency postprocess options."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel

class IntermittencyPostprocessConfig(BaseModel):
    """Intermittency indicators derived from flow accumulation flux."""

    model_config = ConfigDict(extra="forbid")

    yearly: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Compute yearly intermittency indicators from accumulation flux.",
    )
    monthly: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Compute monthly intermittency indicators from accumulation flux.",
    )
    weekly: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Compute weekly intermittency indicators from accumulation flux.",
    )
    daily: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Compute daily intermittency indicators from accumulation flux.",
    )


__all__ = ["IntermittencyPostprocessConfig"]
