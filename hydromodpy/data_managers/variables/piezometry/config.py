"""Pydantic configuration for piezometry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.data_managers.common.base_config import BaseVariableConfig


class PiezometrySourceConfig(BaseModel):
    """Configuration for ONE piezometry data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "hubeau"], ParamLevel("user")] = Field(
        ..., description="Data provider."
    )

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: Annotated[str, ParamLevel("dev")] = Field(default="id", description="Column name for piezometer identifier.")
    col_x: Annotated[str, ParamLevel("dev")] = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: Annotated[str, ParamLevel("dev")] = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: Annotated[str, ParamLevel("dev")] = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: Annotated[str, ParamLevel("dev")] = Field(default="EPSG:4326", description="Default CRS.")
    col_datetime: Annotated[str, ParamLevel("dev")] = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: Annotated[str, ParamLevel("dev")] = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Annotated[Optional[Literal["level", "depth"]], ParamLevel("user")] = Field(
        default=None, description="Hub'Eau measurement type: 'level' or 'depth'."
    )
    require_observations: Annotated[bool, ParamLevel("dev")] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[Optional[float], ParamLevel("dev")] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Annotated[Optional[list[str]], ParamLevel("user")] = Field(default=None, description="Explicit station ids.")
    extent: Annotated[Optional[Literal["watershed", "study_area"]], ParamLevel("user")] = Field(
        default=None,
        description="Enable bbox-based station discovery using the project extent.",
    )
    nearest: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Keep only the nearest piezometer to the extent centroid.",
    )
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )
    source_unit: Annotated[Optional[str], ParamLevel("dev")] = Field(
        default=None, description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit."
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "PiezometrySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        if self.source == "hubeau":
            if self.product is None:
                raise ValueError("Hub'Eau source requires 'product' ('level' or 'depth').")
        return self


class PiezometryConfig(BaseVariableConfig):
    """Top-level piezometry configuration."""

    _TOML_SECTION = "piezometry"

    sources: Annotated[list[PiezometrySourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source."
    )
