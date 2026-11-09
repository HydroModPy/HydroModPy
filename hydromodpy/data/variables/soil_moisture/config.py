"""Pydantic configuration for soil moisture data sources."""

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


class SoilMoistureSourceConfig(UrlSourceFieldsMixin, Sim2GridSourceConfig):
    """Configuration for one soil-moisture data source.

    Soil-moisture sources load station or gridded soil-moisture indices from
    custom files or SIM2 EDR products. Source-level fields define file paths,
    station columns, masks, units, and cache refresh behavior.
    """

    VARIABLE_NAME: ClassVar[str] = "soil_moisture"

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="soil_moisture", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class SoilMoistureConfig(BaseVariableConfig):
    """Top-level soil-moisture configuration.

    The section groups soil-moisture sources and an optional date window.
    Loaded data can support hydrological diagnostics and land-surface forcing
    analyses.
    """

    _TOML_SECTION = "soil_moisture"

    sources: Annotated[list[SoilMoistureSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
