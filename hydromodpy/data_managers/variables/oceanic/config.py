"""Pydantic configuration for oceanic data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.config.path_resolution import resolve_declared_path


class OceanicSourceConfig(BaseModel):
    """Configuration for ONE oceanic data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "shom", "constant"], ParamLevel("user")] = Field(
        ..., description="Data provider: 'custom' for user CSV/NC/TIF files, 'shom' for SHOM API, 'constant' for fixed MSL.",
    )

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
    )
    col_id: Annotated[str, ParamLevel("dev")] = Field(default="id", description="Column name for station identifier in location file.")
    col_x: Annotated[str, ParamLevel("dev")] = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: Annotated[str, ParamLevel("dev")] = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: Annotated[str, ParamLevel("dev")] = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: Annotated[str, ParamLevel("dev")] = Field(default="EPSG:4326", description="Default CRS when not specified in location file.")
    col_datetime: Annotated[str, ParamLevel("dev")] = Field(default="datetime", description="Column name for datetime in chronicle CSVs.")
    col_value: Annotated[str, ParamLevel("dev")] = Field(default="value", description="Column name for value in chronicle CSVs.")

    # --- Constant source fields ---
    value: Annotated[Optional[float], ParamLevel("user")] = Field(
        default=None, description="Constant mean sea-level value in metres.",
    )

    # --- SHOM API fields ---
    nearest: Annotated[bool, ParamLevel("dev")] = Field(
        default=True, description="Use nearest tide gauge to watershed centroid.",
    )
    fallback_search_radius_km: Annotated[Optional[float], ParamLevel("dev")] = Field(
        default=None, description="Maximum search radius (km) for nearest tide gauge.",
    )
    require_observations: Annotated[bool, ParamLevel("dev")] = Field(
        default=True, description="Raise if SHOM returns no observations.",
    )

    # --- Spatial mask ---
    mask_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    # --- Common fields ---
    station_ids: Annotated[Optional[list[str]], ParamLevel("user")] = Field(
        default=None, description="Explicit station ids to load (custom source).",
    )
    extent: Annotated[Optional[Literal["watershed", "study_area"]], ParamLevel("user")] = Field(
        default=None, description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False, description="Ignore cache and re-download from API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "OceanicSourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError("Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file).")
        if self.source == "constant":
            if self.value is None:
                raise ValueError("Constant source requires 'value' (mean sea-level in metres).")
        return self


class OceanicConfig(BaseModel):
    """Top-level oceanic configuration."""

    model_config = ConfigDict(extra="forbid")

    sources: Annotated[list[OceanicSourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source.",
    )
    date_start: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None, description="Project start date (ISO format, e.g. '2003-01-01').",
    )
    date_end: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None, description="Project end date (ISO format, e.g. '2003-01-30').",
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

    @model_validator(mode="after")
    def _check_date_order(self) -> "OceanicConfig":
        if self.date_start and self.date_end:
            from datetime import datetime
            if datetime.fromisoformat(self.date_start) >= datetime.fromisoformat(self.date_end):
                raise ValueError("date_start must be before date_end")
        return self

    @classmethod
    def from_toml(cls, path: str | Path) -> "OceanicConfig":
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
        section = data.get("oceanic", data)
        cfg = cls.model_validate(section)
        _resolve_paths(cfg, path.parent)
        return cfg


def _resolve_paths(cfg: "OceanicConfig", toml_dir: Path) -> None:
    """Resolve relative paths in source configs relative to the TOML directory."""
    for src in cfg.sources:
        if src.path is not None:
            src.path = resolve_declared_path(src.path, base_dir=toml_dir)
        if src.mask_path is not None:
            src.mask_path = resolve_declared_path(src.mask_path, base_dir=toml_dir)
