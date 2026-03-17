"""Pydantic configuration for piezometry data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.config.path_resolution import resolve_declared_path


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

    sources: Annotated[list[PiezometrySourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source."
    )
    date_start: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None, description="Project start date (ISO format, e.g. '2019-01-01')."
    )
    date_end: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None, description="Project end date (ISO format, e.g. '2025-12-31')."
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
    def _check_date_order(self) -> "PiezometryConfig":
        if self.date_start and self.date_end:
            from datetime import datetime
            if datetime.fromisoformat(self.date_start) >= datetime.fromisoformat(self.date_end):
                raise ValueError("date_start must be before date_end")
        return self

    @classmethod
    def from_toml(cls, path: str | Path) -> "PiezometryConfig":
        """Load config from a TOML file.

        Relative paths (``path``, ``mask_path``) are resolved relative
        to the TOML file's directory.
        """
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
        section = data.get("piezometry", data)
        cfg = cls.model_validate(section)
        _resolve_paths(cfg, path.parent)
        return cfg


def _resolve_paths(cfg: "PiezometryConfig", toml_dir: Path) -> None:
    """Resolve relative paths in source configs relative to the TOML directory."""
    for src in cfg.sources:
        if src.path is not None:
            src.path = resolve_declared_path(src.path, base_dir=toml_dir)
        if src.mask_path is not None:
            src.mask_path = resolve_declared_path(src.mask_path, base_dir=toml_dir)
