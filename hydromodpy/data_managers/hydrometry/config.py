"""Pydantic configuration for hydrometry data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HydrometrySourceConfig(BaseModel):
    """Configuration for ONE hydrometry data source."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "hubeau"] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

    # --- Custom source fields ---
    path: Optional[Path] = Field(
        default=None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: str = Field(default="id", description="Column name for station identifier in location file.")
    col_x: str = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: str = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: str = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: str = Field(default="EPSG:4326", description="Default CRS when not specified in location file.")
    col_datetime: str = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: str = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Optional[Path] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Optional[str] = Field(
        default=None,
        description="Hub'Eau variable code (e.g. 'QmnJ', 'QmM', 'HmnJ').",
    )
    require_observations: bool = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Optional[float] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Optional[list[str]] = Field(
        default=None, description="Explicit list of station ids to load."
    )
    extent: Optional[Literal["watershed", "study_area"]] = Field(
        default=None, description="Spatial selection mode."
    )
    force_refresh: bool = Field(default=False, description="Ignore cache and re-download.")

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


class HydrometryConfig(BaseModel):
    """Top-level hydrometry configuration (list of sources)."""

    model_config = ConfigDict(extra="forbid")

    sources: list[HydrometrySourceConfig] = Field(
        ..., min_length=1, description="At least one data source."
    )
    date_start: Optional[str] = Field(
        default=None, description="Project start date (ISO format, e.g. '2019-01-01')."
    )
    date_end: Optional[str] = Field(
        default=None, description="Project end date (ISO format, e.g. '2025-12-31')."
    )

    @classmethod
    def from_toml(cls, path: str | Path) -> "HydrometryConfig":
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
        section = data.get("hydrometry", data)
        return cls.model_validate(section)
