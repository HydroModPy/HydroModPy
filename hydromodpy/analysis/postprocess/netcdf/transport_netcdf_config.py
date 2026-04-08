"""Pydantic schema for transport NetCDF postprocess options."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel


class TransportNetcdfPostprocessConfig(BaseModel):
    """Transport NetCDF export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Enable transport NetCDF export after transport runs.",
    )
    datetime_format: Annotated[bool, ParamLevel("dev")] = Field(
        default=True,
        description="Format NetCDF time axis as datetimes when possible.",
    )
    residence_times: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Export residence-time NetCDF derived from particle outputs.",
    )
    concentration_seepage: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Export concentration seepage NetCDF from transport outputs.",
    )
    mass_accumulated: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Export accumulated mass NetCDF from transport outputs.",
    )


__all__ = [
    "TransportNetcdfPostprocessConfig",
]

