"""Pydantic configuration for piezometry data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PiezometrySourceConfig(BaseModel):
    """Configuration for ONE piezometry data source."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "hubeau"] = Field(
        ..., description="Data provider."
    )

    # --- Custom source fields ---
    path: Optional[Path] = Field(
        default=None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: str = Field(default="id", description="Column name for piezometer identifier.")
    col_x: str = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: str = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: str = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: str = Field(default="EPSG:4326", description="Default CRS.")
    col_datetime: str = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: str = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Optional[Path] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Optional[Literal["level", "depth"]] = Field(
        default=None, description="Hub'Eau measurement type: 'level' or 'depth'."
    )
    require_observations: bool = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Optional[float] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Optional[list[str]] = Field(default=None, description="Explicit station ids.")
    extent: Optional[Literal["watershed", "study_area"]] = Field(default=None)
    nearest: bool = Field(
        default=False,
        description="Include the nearest piezometer even if outside the extent.",
    )
    force_refresh: bool = Field(default=False)

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


class PiezometryConfig(BaseModel):
    """Top-level piezometry configuration."""

    model_config = ConfigDict(extra="forbid")

    sources: list[PiezometrySourceConfig] = Field(
        ..., min_length=1, description="At least one data source."
    )
    date_start: Optional[str] = Field(
        default=None, description="Project start date (ISO format, e.g. '2019-01-01')."
    )
    date_end: Optional[str] = Field(
        default=None, description="Project end date (ISO format, e.g. '2025-12-31')."
    )

    @classmethod
    def from_toml(cls, path: str | Path) -> "PiezometryConfig":
        """Load config from a TOML file."""
        path = Path(path)
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
        section = data.get("piezometry", data)
        return cls.model_validate(section)
