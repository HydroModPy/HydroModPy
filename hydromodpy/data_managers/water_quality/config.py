"""Pydantic configuration for water quality data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WaterQualitySourceConfig(BaseModel):
    """Configuration for ONE water quality data source."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "hubeau"] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

    # --- Site type (river vs piezometer quality) ---
    site_type: Literal["river", "piezometer"] = Field(
        "river", description="Type of site: 'river' (qualite_rivieres) or 'piezometer' (qualite_nappes)."
    )

    # --- Parameter filtering ---
    parameters: Optional[list[str]] = Field(
        None,
        description="Parameters to keep (e.g. ['pH', 'Nitrates']). None = all parameters.",
    )

    # --- Custom source fields ---
    path: Optional[Path] = Field(
        None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: str = Field("id", description="Column name for station identifier in location file.")
    col_x: str = Field("x", description="Column name for X coordinate in location CSV.")
    col_y: str = Field("y", description="Column name for Y coordinate in location CSV.")
    col_crs: str = Field("crs", description="Column name for CRS in location CSV.")
    default_crs: str = Field("EPSG:4326", description="Default CRS when not in location file.")
    col_datetime: str = Field("datetime", description="Column name for datetime in chronicles.")
    col_value: str = Field("value", description="Column name for value in chronicles.")
    source_unit: str = Field("mg/L", description="Unit of the source data.")
    target_unit: str = Field("mg/L", description="Target unit after conversion.")

    # Fixed value (alternative to chronicle files)
    fixed_value: Optional[float] = Field(None, description="Single constant value.")
    fixed_values: Optional[dict[str, float]] = Field(None, description="Per-station constants.")

    # --- Spatial mask ---
    mask_path: Optional[Path] = Field(
        None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- Common fields ---
    station_ids: Optional[list[str]] = Field(None, description="Explicit station ids.")
    extent: Optional[Literal["watershed", "study_area"]] = Field(None)
    force_refresh: bool = Field(False, description="Ignore cache and re-download.")

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "WaterQualitySourceConfig":
        if self.source == "custom":
            if self.path is None and self.fixed_value is None and self.fixed_values is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles) "
                    "or 'fixed_value'/'fixed_values'."
                )
        return self


class WaterQualityConfig(BaseModel):
    """Top-level water quality configuration (list of sources)."""

    model_config = ConfigDict(extra="forbid")

    sources: list[WaterQualitySourceConfig] = Field(
        ..., min_length=1, description="At least one data source."
    )

    @classmethod
    def from_toml(cls, path: str | Path) -> "WaterQualityConfig":
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
        section = data.get("water_quality", data)
        return cls.model_validate(section)
