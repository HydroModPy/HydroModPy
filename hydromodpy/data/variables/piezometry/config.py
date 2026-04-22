"""Pydantic configuration for piezometry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.base_config import BaseVariableConfig


class PiezometrySourceConfig(HydroModelBase):
    """Configuration for ONE piezometry data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "hubeau"], Profile.USER] = Field(
        ..., description="Data provider."
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="piezometry", category="data"),
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")
    col_id: Annotated[str, Profile.DEV] = Field(
        default="id", description="Column name for piezometer identifier."
    )
    col_x: Annotated[str, Profile.DEV] = Field(
        default="x", description="Column name for X coordinate in location CSV."
    )
    col_y: Annotated[str, Profile.DEV] = Field(
        default="y", description="Column name for Y coordinate in location CSV."
    )
    col_crs: Annotated[str, Profile.DEV] = Field(
        default="crs", description="Column name for CRS in location CSV."
    )
    default_crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:4326", description="Default CRS."
    )
    col_datetime: Annotated[str, Profile.DEV] = Field(
        default="datetime", description="Column name for datetime in chronicle CSVs."
    )
    col_value: Annotated[str, Profile.DEV] = Field(
        default="value", description="Column name for value in chronicle CSVs."
    )

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Annotated[Literal["level", "depth"] | None, Profile.USER] = Field(
        default=None, description="Hub'Eau measurement type: 'level' or 'depth'."
    )
    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, Profile.USER] = Field(
        default=None, description="Explicit station ids."
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.USER] = Field(
        default=None,
        description="Enable bbox-based station discovery using the project extent.",
    )
    nearest: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep only the nearest piezometer to the extent centroid.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> PiezometrySourceConfig:
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

    sources: Annotated[list[PiezometrySourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
