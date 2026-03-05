"""Pydantic schema for flow NetCDF postprocess options."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FlowNetcdfPostprocessConfig(BaseModel):
    """Flow NetCDF export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Enable flow NetCDF export after the flow process family.",
    )
    datetime_format: bool = Field(
        default=True,
        description="Format NetCDF time axis as datetimes when possible.",
    )


__all__ = [
    "FlowNetcdfPostprocessConfig",
]

