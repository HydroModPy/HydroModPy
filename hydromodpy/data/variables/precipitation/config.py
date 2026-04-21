"""Pydantic configuration for precipitation data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.profile import Profile
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.core.config.base import HydroModelBase


class PrecipitationSourceConfig(HydroModelBase):
    """Configuration for ONE precipitation data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "sim2"], Profile.USER] = Field(
        ..., description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API.",
    )

    # --- Precipitation-specific ---
    components: Annotated[list[Literal["liquid", "solid", "total"]], Profile.USER] = Field(
        default=["total"],
        min_length=1,
        description="Precipitation components: 'liquid' (rain), 'solid' (snow), 'total' (sum of both).",
    )

    # --- Custom source fields ---
    path: Annotated[Path | None, Profile.USER] = Field(default=None, description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.")
    source_unit: Annotated[str | None, Profile.USER] = Field(default=None, description="Optional source unit for custom gridded .nc/.tif inputs. If omitted for NetCDF, units are inferred from variable metadata when available.")
    col_id: Annotated[str, Profile.DEV] = Field(default="id", description="Column name for station identifier in location file.")
    col_x: Annotated[str, Profile.DEV] = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: Annotated[str, Profile.DEV] = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: Annotated[str, Profile.DEV] = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: Annotated[str, Profile.DEV] = Field(default="EPSG:4326", description="Default CRS when not specified in location file.")
    col_datetime: Annotated[str, Profile.DEV] = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: Annotated[str, Profile.DEV] = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.")

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, Profile.USER] = Field(default=None, description="Explicit station ids (custom source).")
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.USER] = Field(
        default=None, description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(default=False, description="Ignore cache and re-download from API.")

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "PrecipitationSourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError("Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file).")
        return self


class PrecipitationConfig(BaseVariableConfig):
    """Top-level precipitation configuration."""

    _TOML_SECTION = "precipitation"

    sources: Annotated[list[PrecipitationSourceConfig], Profile.USER] = Field(..., min_length=1, description="At least one data source.")
