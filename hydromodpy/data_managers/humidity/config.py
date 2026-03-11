"""Pydantic configuration for humidity data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel


class HumiditySourceConfig(BaseModel):
    """Configuration for ONE humidity data source."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "sim2"] = Field(
        ..., description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API.",
    )

    # --- Custom source fields ---
    path: Optional[Path] = Field(
        default=None, description="Directory containing location file and chronicle CSVs.",
    )
    col_id: Annotated[str, ParamLevel("dev")] = Field(default="id", description="Column name for station identifier in location file.")
    col_x: Annotated[str, ParamLevel("dev")] = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: Annotated[str, ParamLevel("dev")] = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: Annotated[str, ParamLevel("dev")] = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: Annotated[str, ParamLevel("dev")] = Field(default="EPSG:4326", description="Default CRS when not specified in location file.")
    col_datetime: Annotated[str, ParamLevel("dev")] = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: Annotated[str, ParamLevel("dev")] = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Optional[Path] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    # --- Common fields ---
    station_ids: Optional[list[str]] = Field(default=None, description="Explicit station ids (custom source).")
    extent: Optional[Literal["watershed", "study_area"]] = Field(
        default=None, description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: bool = Field(
        default=False, description="Ignore cache and re-download from API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "HumiditySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError("Custom source requires 'path' (directory with location + chronicles).")
        return self


class HumidityConfig(BaseModel):
    """Top-level humidity configuration."""

    model_config = ConfigDict(extra="forbid")

    sources: list[HumiditySourceConfig] = Field(
        ..., min_length=1, description="At least one data source.",
    )
    date_start: Optional[str] = Field(
        default=None, description="Project start date (ISO format, e.g. '2019-01-01').",
    )
    date_end: Optional[str] = Field(
        default=None, description="Project end date (ISO format, e.g. '2025-12-31').",
    )

    @field_validator("date_start", "date_end", mode="after")
    @classmethod
    def _validate_iso_date(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            from datetime import datetime
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Invalid ISO date: '{v}'. Expected YYYY-MM-DD.")
        return v

    @classmethod
    def from_toml(cls, path: str | Path) -> "HumidityConfig":
        """Load config from a TOML file."""
        path = Path(path).resolve()
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
        section = data.get("humidity", data)
        cfg = cls.model_validate(section)
        _resolve_paths(cfg, path.parent)
        return cfg


def _resolve_paths(cfg: "HumidityConfig", toml_dir: Path) -> None:
    for src in cfg.sources:
        if src.path is not None and not src.path.is_absolute():
            src.path = (toml_dir / src.path).resolve()
        if src.mask_path is not None and not src.mask_path.is_absolute():
            src.mask_path = (toml_dir / src.mask_path).resolve()
