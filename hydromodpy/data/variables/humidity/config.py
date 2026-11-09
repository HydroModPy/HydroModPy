"""Pydantic configuration for humidity data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import (
    Sim2GridSourceConfig,
    UrlSourceFieldsMixin,
)


class HumiditySourceConfig(UrlSourceFieldsMixin, Sim2GridSourceConfig):
    """Configuration for one relative-humidity data source.

    Humidity sources load station or gridded relative-humidity time series from
    custom files or SIM2 EDR products. Source-level fields define file paths,
    station columns, masks, units, and cache refresh behavior.
    """

    VARIABLE_NAME: ClassVar[str] = "humidity"

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="humidity", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class HumidityConfig(BaseVariableConfig):
    """Top-level relative-humidity configuration.

    The section groups humidity sources and an optional date window. Loaded data
    can support atmospheric forcing, evapotranspiration context, and HELP
    coupling.
    """

    _TOML_SECTION = "humidity"

    sources: Annotated[list[HumiditySourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
