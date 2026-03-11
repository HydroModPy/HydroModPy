"""Pydantic schema for flow timeseries postprocess options."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FlowTimeseriesPostprocessConfig(BaseModel):
    """Flow-timeseries export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable flow timeseries export after the flow process family.",
    )
    datetime_format: bool = Field(
        default=True,
        description="Format exported timeseries index as datetimes when possible.",
    )
    subbasin_results: bool = Field(
        default=True,
        description="Also export one timeseries file per available subbasin.",
    )


__all__ = ["FlowTimeseriesPostprocessConfig"]
