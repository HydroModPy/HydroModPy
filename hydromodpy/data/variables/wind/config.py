"""Pydantic configuration for wind data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import Sim2GridSourceConfig


class WindSourceConfig(Sim2GridSourceConfig):
    """Configuration for one wind-speed data source.

    Wind sources load station or gridded wind-speed time series from custom
    files or SIM2 EDR products. Source-level fields define file paths, station
    columns, masks, units, and cache refresh behavior.
    """

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="wind", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class WindConfig(BaseVariableConfig):
    """Top-level wind-speed configuration.

    The section groups wind sources and an optional date window. Loaded data can
    support atmospheric forcing, evapotranspiration context, and HELP coupling.
    """

    _TOML_SECTION = "wind"

    sources: Annotated[list[WindSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
