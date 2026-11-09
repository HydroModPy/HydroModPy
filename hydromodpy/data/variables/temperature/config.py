"""Pydantic configuration for temperature data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    Sim2GridSourceConfig,
    UrlSourceFieldsMixin,
)


class TemperatureSourceConfig(UrlSourceFieldsMixin, Sim2GridSourceConfig):
    """Configuration for one air-temperature data source.

    Temperature sources load station or gridded air-temperature time series
    from custom files or SIM2 EDR products. Source-level fields define file
    paths, station columns, masks, units, and cache refresh behavior.
    """

    VARIABLE_NAME: ClassVar[str] = "temperature"

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="temperature", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class TemperatureConfig(BaseVariableConfig):
    """Top-level air-temperature configuration.

    The section groups temperature sources and an optional date window. Loaded
    data can support atmospheric forcing, HELP coupling, and diagnostic
    analyses.
    """

    _TOML_SECTION = "temperature"

    sources: Annotated[list[TemperatureSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
