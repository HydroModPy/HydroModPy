"""Pydantic configuration for recharge data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.core.config.base import HydroModelBase


class RechargeSourceConfig(HydroModelBase):
    """Configuration for ONE recharge data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "sim2", "synthetic"], ParamLevel("user")] = Field(
        ..., description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API, 'synthetic' for generated series.",
    )

    # --- Custom source fields ---
    path: Annotated[Path | None, ParamLevel("user")] = Field(
        default=None, description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
    )
    source_unit: Annotated[str | None, ParamLevel("user")] = Field(
        default=None, description="Optional source unit for custom gridded .nc/.tif inputs. If omitted for NetCDF, units are inferred from variable metadata when available.",
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
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    # --- Synthetic source fields ---
    values: Annotated[list[float] | None, ParamLevel("user")] = Field(
        default=None, description="Recharge values in mm/day. Single value for constant, list for time-varying.",
    )
    start_date: Annotated[str | None, ParamLevel("user")] = Field(
        default=None, description="Start date for synthetic series (ISO format, e.g. '2020-01-01').",
    )
    freq: Annotated[str | None, ParamLevel("dev")] = Field(
        default=None, description="Frequency for synthetic series (e.g. 'D', 'ME', 'YE').",
    )
    periods: Annotated[int | None, ParamLevel("dev")] = Field(
        default=None, description="Number of periods for synthetic series.",
    )
    amplitude: Annotated[float | None, ParamLevel("expert")] = Field(
        default=None, description="Sinusoidal amplitude in mm/day (superimposed on values).",
    )
    period_days: Annotated[int | None, ParamLevel("expert")] = Field(
        default=None, description="Sinusoidal period in days.",
    )
    offset: Annotated[float | None, ParamLevel("expert")] = Field(
        default=None, description="Sinusoidal baseline offset in mm/day.",
    )
    runoff_ratio: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None, description="Fraction of recharge routed to runoff (0.0 to 1.0).",
    )

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, ParamLevel("user")] = Field(default=None, description="Explicit station ids (custom source).")
    extent: Annotated[Literal["watershed", "study_area"] | None, ParamLevel("user")] = Field(
        default=None, description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False, description="Ignore cache and re-download from API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "RechargeSourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError("Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file).")
        if self.source == "synthetic":
            if self.values is None:
                raise ValueError("Synthetic source requires 'values' (list of recharge values in mm/day).")
        return self


class RechargeConfig(BaseVariableConfig):
    """Top-level recharge configuration."""

    _TOML_SECTION = "recharge"

    sources: Annotated[list[RechargeSourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source.",
    )
