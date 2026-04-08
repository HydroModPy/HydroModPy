"""Pydantic schema for flow NetCDF postprocess options."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel


class FlowNetcdfPostprocessConfig(BaseModel):
    """Flow NetCDF export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Enable flow NetCDF export after the flow process family.",
    )
    datetime_format: Annotated[bool, ParamLevel("dev")] = Field(
        default=True,
        description="Format NetCDF time axis as datetimes when possible.",
    )


__all__ = [
    "FlowNetcdfPostprocessConfig",
]

