"""Pydantic configuration for recharge data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel


class RechargeSourceConfig(BaseModel):
    """Configuration for ONE recharge data source."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "sim2", "synthetic"] = Field(
        ..., description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API, 'synthetic' for generated series.",
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

    # --- Synthetic source fields ---
    values: Optional[list[float]] = Field(
        default=None, description="Recharge values in mm/day. Single value for constant, list for time-varying.",
    )
    start_date: Optional[str] = Field(
        default=None, description="Start date for synthetic series (ISO format, e.g. '2020-01-01').",
    )
    freq: Optional[str] = Field(
        default=None, description="Frequency for synthetic series (e.g. 'D', 'ME', 'YE').",
    )
    periods: Optional[int] = Field(
        default=None, description="Number of periods for synthetic series.",
    )
    amplitude: Optional[float] = Field(
        default=None, description="Sinusoidal amplitude in mm/day (superimposed on values).",
    )
    period_days: Optional[int] = Field(
        default=None, description="Sinusoidal period in days.",
    )
    offset: Optional[float] = Field(
        default=None, description="Sinusoidal baseline offset in mm/day.",
    )
    runoff_ratio: Optional[float] = Field(
        default=None, description="Fraction of recharge routed to runoff (0.0 to 1.0).",
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
    def _check_source_requirements(self) -> "RechargeSourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError("Custom source requires 'path' (directory with location + chronicles).")
        if self.source == "synthetic":
            if self.values is None:
                raise ValueError("Synthetic source requires 'values' (list of recharge values in mm/day).")
        return self


class RechargeConfig(BaseModel):
    """Top-level recharge configuration."""

    model_config = ConfigDict(extra="forbid")

    sources: list[RechargeSourceConfig] = Field(
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
    def from_toml(cls, path: str | Path) -> "RechargeConfig":
        """Load config from a TOML file.

        Relative paths are resolved relative to the TOML file's directory.
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
        section = data.get("recharge", data)
        cfg = cls.model_validate(section)
        _resolve_paths(cfg, path.parent)
        return cfg


def _resolve_paths(cfg: "RechargeConfig", toml_dir: Path) -> None:
    """Resolve relative paths in source configs relative to the TOML directory."""
    for src in cfg.sources:
        if src.path is not None and not src.path.is_absolute():
            src.path = (toml_dir / src.path).resolve()
        if src.mask_path is not None and not src.mask_path.is_absolute():
            src.mask_path = (toml_dir / src.mask_path).resolve()
