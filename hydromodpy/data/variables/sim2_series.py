"""Wind, humidity, runoff, soil moisture and temperature, the SIM2 series variables.

Each one reads station or gridded series from the user's files or from the SIM2
EDR products. The five differ by name, unit and the words of their descriptions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.grids import GridVariable
from hydromodpy.data.families.timeseries_config import (
    Sim2GridSourceConfig,
    UrlSourceFieldsMixin,
)

# --- Wind speed ------------------------------------------------------------


class WindSourceConfig(UrlSourceFieldsMixin, Sim2GridSourceConfig):
    """Configuration for one wind-speed data source.

    Wind sources load station or gridded wind-speed time series from custom
    files or SIM2 EDR products. Source-level fields define file paths, station
    columns, masks, units, and cache refresh behavior.
    """

    VARIABLE_NAME: ClassVar[str] = "wind"

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


class WindVariable(GridVariable):
    VARIABLE_NAME = "wind"
    INTERNAL_UNIT = "m/s"


# --- Relative humidity -----------------------------------------------------


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


class HumidityVariable(GridVariable):
    VARIABLE_NAME = "humidity"
    INTERNAL_UNIT = "%"


# --- Surface runoff --------------------------------------------------------


class RunoffSourceConfig(UrlSourceFieldsMixin, Sim2GridSourceConfig):
    """Configuration for one runoff data source.

    Runoff sources load station or gridded surface-runoff time series from
    custom files or SIM2 EDR products. Source-level fields define file paths,
    station columns, masks, units, and cache refresh behavior.
    """

    VARIABLE_NAME: ClassVar[str] = "runoff"

    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="runoff", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )


class RunoffConfig(BaseVariableConfig):
    """Top-level runoff configuration.

    The section groups runoff sources and an optional date window. Loaded data
    can support hydrological forcing, recharge/runoff partitioning checks, and
    diagnostic comparisons.
    """

    _TOML_SECTION = "runoff"

    sources: Annotated[list[RunoffSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )


class RunoffVariable(GridVariable):
    VARIABLE_NAME = "runoff"
    INTERNAL_UNIT = "mm/day"


# --- Soil moisture index ---------------------------------------------------


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


class SoilMoistureVariable(GridVariable):
    VARIABLE_NAME = "soil_moisture"
    INTERNAL_UNIT = "%"


# --- Air temperature -------------------------------------------------------


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


class TemperatureVariable(GridVariable):
    VARIABLE_NAME = "temperature"
    INTERNAL_UNIT = "degC"
