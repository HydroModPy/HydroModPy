"""Pydantic configuration for intermittency (ONDE) data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.data_managers.common.base_config import BaseVariableConfig


class IntermittencySourceConfig(BaseModel):
    """Configuration for ONE intermittency data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "hubeau"], ParamLevel("user")] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau stream-flow API."
    )

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: Annotated[str, ParamLevel("dev")] = Field(default="id", description="Column name for station identifier in location file.")
    col_x: Annotated[str, ParamLevel("dev")] = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: Annotated[str, ParamLevel("dev")] = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: Annotated[str, ParamLevel("dev")] = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: Annotated[str, ParamLevel("dev")] = Field(default="EPSG:4326", description="Default CRS when not specified in location file.")
    col_datetime: Annotated[str, ParamLevel("dev")] = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: Annotated[str, ParamLevel("dev")] = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    code_departement: Annotated[Optional[list[str]], ParamLevel("user")] = Field(
        default=None,
        description="INSEE department codes to filter Hub'Eau station discovery.",
    )
    require_observations: Annotated[bool, ParamLevel("dev")] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[Optional[float], ParamLevel("dev")] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Annotated[Optional[list[str]], ParamLevel("user")] = Field(
        default=None, description="Explicit list of station codes (code_station) to load."
    )
    extent: Annotated[Optional[Literal["watershed", "study_area"]], ParamLevel("user")] = Field(
        default=None,
        description="Enable bbox-based station discovery using the project extent.",
    )
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "IntermittencySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        return self


class IntermittencyConfig(BaseVariableConfig):
    """Top-level intermittency configuration (list of sources)."""

    _TOML_SECTION = "intermittency"

    sources: Annotated[list[IntermittencySourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source."
    )
