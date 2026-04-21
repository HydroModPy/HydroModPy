"""Pydantic configuration for hydrometry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.core.config.base import HydroModelBase


class HydrometrySourceConfig(HydroModelBase):
    """Configuration for ONE hydrometry data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "hubeau"], ParamLevel("user")] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

    # --- Custom source fields ---
    path: Annotated[Path | None, ParamLevel("user")] = Field(
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
    mask_path: Annotated[Path | None, ParamLevel("user")] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Annotated[str | None, ParamLevel("user")] = Field(
        default=None,
        description="Hub'Eau variable code (e.g. 'QmnJ', 'QmM', 'HmnJ').",
    )
    require_observations: Annotated[bool, ParamLevel("dev")] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, ParamLevel("user")] = Field(
        default=None, description="Explicit list of station ids to load."
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, ParamLevel("user")] = Field(
        default=None,
        description="Enable bbox-based station discovery using the project extent.",
    )
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )
    source_unit: Annotated[str | None, ParamLevel("user")] = Field(
        default=None, description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit."
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "HydrometrySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        if self.source == "hubeau":
            if self.product is None:
                raise ValueError("Hub'Eau source requires 'product' (e.g. 'QmnJ').")
        return self


class HydrometryConfig(BaseVariableConfig):
    """Top-level hydrometry configuration (list of sources)."""

    _TOML_SECTION = "hydrometry"

    sources: Annotated[list[HydrometrySourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source."
    )
