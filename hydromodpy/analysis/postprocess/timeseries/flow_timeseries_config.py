"""Pydantic schema for flow timeseries postprocess options."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel


class FlowTimeseriesPostprocessConfig(BaseModel):
    """Flow-timeseries export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Enable flow timeseries export after the flow process family.",
    )
    datetime_format: Annotated[bool, ParamLevel("dev")] = Field(
        default=True,
        description="Format exported timeseries index as datetimes when possible.",
    )
    subbasin_results: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Also export one timeseries file per available subbasin.",
    )


__all__ = ["FlowTimeseriesPostprocessConfig"]
