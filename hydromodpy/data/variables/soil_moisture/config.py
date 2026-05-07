"""Pydantic configuration for soil moisture data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.data.variables.timeseries_variable_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class SoilMoistureSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one soil-moisture data source.

    Soil-moisture sources load station or gridded soil-moisture indices from
    custom files or SIM2 EDR products. Source-level fields define file paths,
    station columns, masks, units, and cache refresh behavior.
    """

    source: Annotated[Literal["custom", "sim2"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API.",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="soil_moisture", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source unit for custom gridded .nc/.tif inputs. If omitted for NetCDF, units are inferred from variable metadata when available.",
    )

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> SoilMoistureSourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        return self


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
