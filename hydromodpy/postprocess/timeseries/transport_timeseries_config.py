"""Pydantic schema for transport timeseries postprocess options."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TransportTimeseriesPostprocessConfig(BaseModel):
    """Transport-timeseries export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable transport timeseries export after transport runs.",
    )
    suffix_name: str = Field(
        default="s1",
        description=(
            "Suffix appended to transport timeseries filenames "
            "(legacy default: 's1')."
        ),
    )
    datetime_format: bool = Field(
        default=True,
        description="Format exported timeseries index as datetimes when possible.",
    )
    subbasin_results: bool = Field(
        default=True,
        description="Also export one timeseries file per available subbasin.",
    )
    residence_times: bool = Field(
        default=True,
        description="Export residence-time indicators from particle tracking outputs.",
    )
    concentration_seepage: bool = Field(
        default=True,
        description="Export seepage concentration indicators from transport outputs.",
    )
    mass_accumulated: bool = Field(
        default=True,
        description="Export accumulated-mass indicators from transport outputs.",
    )


__all__ = ["TransportTimeseriesPostprocessConfig"]
