"""Pydantic configuration for water quality data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.data.common.base_config import BaseVariableConfig


class WaterQualitySourceConfig(BaseModel):
    """Configuration for ONE water quality data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "hubeau"], ParamLevel("user")] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

    # --- Site type (river vs piezometer quality) ---
    site_type: Annotated[Literal["river", "piezometer"], ParamLevel("user")] = Field(
        default="river", description="Type of site: 'river' (qualite_rivieres) or 'piezometer' (qualite_nappes)."
    )

    # --- Parameter filtering ---
    parameters: Annotated[list[str] | None, ParamLevel("user")] = Field(
        default=None,
        description="Parameters to keep (e.g. ['pH', 'Nitrates']). None = all parameters.",
    )

    # --- Custom source fields ---
    path: Annotated[Path | None, ParamLevel("user")] = Field(
        default=None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: Annotated[str, ParamLevel("dev")] = Field(default="id", description="Column name for station identifier in location file.")
    col_x: Annotated[str, ParamLevel("dev")] = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: Annotated[str, ParamLevel("dev")] = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: Annotated[str, ParamLevel("dev")] = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: Annotated[str, ParamLevel("dev")] = Field(default="EPSG:4326", description="Default CRS when not in location file.")
    col_datetime: Annotated[str, ParamLevel("dev")] = Field(default="datetime", description="Column name for datetime in chronicles.")
    col_value: Annotated[str, ParamLevel("dev")] = Field(default="value", description="Column name for value in chronicles.")

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, ParamLevel("user")] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API fallback / nearest ---
    fallback_search_radius_km: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )
    nearest: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Keep only the nearest station to the extent centroid.",
    )

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, ParamLevel("user")] = Field(default=None, description="Explicit station ids.")
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
    def _check_source_requirements(self) -> "WaterQualitySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        return self


class WaterQualityConfig(BaseVariableConfig):
    """Top-level water quality configuration (list of sources)."""

    _TOML_SECTION = "water_quality"

    sources: Annotated[list[WaterQualitySourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source."
    )
