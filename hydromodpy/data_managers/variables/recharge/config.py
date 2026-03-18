"""Pydantic configuration for recharge data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.data_managers.common.base_config import BaseVariableConfig


class RechargeSourceConfig(BaseModel):
    """Configuration for ONE recharge data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "sim2", "synthetic"], ParamLevel("user")] = Field(
        ..., description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API, 'synthetic' for generated series.",
    )

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
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
    mask_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    # --- Synthetic source fields ---
    values: Annotated[Optional[list[float]], ParamLevel("user")] = Field(
        default=None, description="Recharge values in mm/day. Single value for constant, list for time-varying.",
    )
    start_date: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None, description="Start date for synthetic series (ISO format, e.g. '2020-01-01').",
    )
    freq: Annotated[Optional[str], ParamLevel("dev")] = Field(
        default=None, description="Frequency for synthetic series (e.g. 'D', 'ME', 'YE').",
    )
    periods: Annotated[Optional[int], ParamLevel("dev")] = Field(
        default=None, description="Number of periods for synthetic series.",
    )
    amplitude: Annotated[Optional[float], ParamLevel("expert")] = Field(
        default=None, description="Sinusoidal amplitude in mm/day (superimposed on values).",
    )
    period_days: Annotated[Optional[int], ParamLevel("expert")] = Field(
        default=None, description="Sinusoidal period in days.",
    )
    offset: Annotated[Optional[float], ParamLevel("expert")] = Field(
        default=None, description="Sinusoidal baseline offset in mm/day.",
    )
    runoff_ratio: Annotated[Optional[float], ParamLevel("dev")] = Field(
        default=None, description="Fraction of recharge routed to runoff (0.0 to 1.0).",
    )

    # --- Common fields ---
    station_ids: Annotated[Optional[list[str]], ParamLevel("user")] = Field(default=None, description="Explicit station ids (custom source).")
    extent: Annotated[Optional[Literal["watershed", "study_area"]], ParamLevel("user")] = Field(
        default=None, description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
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


class RechargeConfig(BaseVariableConfig):
    """Top-level recharge configuration."""

    _TOML_SECTION = "recharge"

    sources: Annotated[list[RechargeSourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one data source.",
    )
