"""Pydantic schema for transport NetCDF postprocess options."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TransportNetcdfPostprocessConfig(BaseModel):
    """Transport NetCDF export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Enable transport NetCDF export after transport runs.",
    )
    datetime_format: bool = Field(
        default=True,
        description="Format NetCDF time axis as datetimes when possible.",
    )
    residence_times: bool = Field(
        default=True,
        description="Export residence-time NetCDF derived from particle outputs.",
    )
    concentration_seepage: bool = Field(
        default=True,
        description="Export concentration seepage NetCDF from transport outputs.",
    )
    mass_accumulated: bool = Field(
        default=True,
        description="Export accumulated mass NetCDF from transport outputs.",
    )


__all__ = [
    "TransportNetcdfPostprocessConfig",
]

