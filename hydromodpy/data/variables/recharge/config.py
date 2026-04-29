"""Pydantic configuration for recharge data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.tracking import InputFile
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.profile import Profile


class RechargeSourceConfig(HydroModelBase):
    """Configuration for ONE recharge data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "sim2", "synthetic"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API, 'synthetic' for generated series.",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="recharge", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source unit for custom gridded .nc/.tif inputs. If omitted for NetCDF, units are inferred from variable metadata when available.",
    )
    col_id: Annotated[str, Profile.DEV] = Field(
        default="id", description="Column name for station identifier in location file."
    )
    col_x: Annotated[str, Profile.DEV] = Field(
        default="x", description="Column name for X coordinate in location CSV."
    )
    col_y: Annotated[str, Profile.DEV] = Field(
        default="y", description="Column name for Y coordinate in location CSV."
    )
    col_crs: Annotated[str, Profile.DEV] = Field(
        default="crs", description="Column name for CRS in location CSV."
    )
    default_crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:4326", description="Default CRS when not specified in location file."
    )
    col_datetime: Annotated[str, Profile.DEV] = Field(
        default="datetime", description="Column name for datetime in chronicle CSVs."
    )
    col_value: Annotated[str, Profile.DEV] = Field(
        default="value", description="Column name for value in chronicle CSVs."
    )

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    # --- Synthetic source fields ---
    values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Recharge values in mm/day. Single value for constant, list for time-varying.",
    )
    start_date: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Start date for synthetic series (ISO format, e.g. '2020-01-01').",
    )
    freq: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Frequency for synthetic series (e.g. 'D', 'ME', 'YE').",
    )
    periods: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Number of periods for synthetic series.",
    )
    amplitude: Annotated[float | None, Profile.EXPERT] = Field(
        default=None,
        description="Sinusoidal amplitude in mm/day (superimposed on values).",
    )
    period_days: Annotated[int | None, Profile.EXPERT] = Field(
        default=None,
        description="Sinusoidal period in days.",
    )
    offset: Annotated[float | None, Profile.EXPERT] = Field(
        default=None,
        description="Sinusoidal baseline offset in mm/day.",
    )
    runoff_ratio: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Fraction of recharge routed to runoff (0.0 to 1.0).",
    )

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, Profile.USER] = Field(
        default=None, description="Explicit station ids (custom source)."
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.USER] = Field(
        default=None,
        description="Enable bbox-based data retrieval using the project extent.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> RechargeSourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        if self.source == "synthetic":
            if self.values is None:
                raise ValueError(
                    "Synthetic source requires 'values' (list of recharge values in mm/day)."
                )
        return self


class RechargeConfig(BaseVariableConfig):
    """Top-level recharge configuration."""

    _TOML_SECTION = "recharge"

    sources: Annotated[list[RechargeSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )

    @classmethod
    def sim2(
        cls,
        *,
        start: str,
        end: str,
        extent: Literal["watershed", "study_area"] = "watershed",
        **overrides,
    ) -> RechargeConfig:
        """RechargeConfig pulling from the SIM2 EDR service for a date window."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[RechargeSourceConfig(source="sim2", extent=extent, **overrides)],
        )

    @classmethod
    def synthetic(
        cls,
        *,
        start: str,
        end: str,
        values: list[float] | float,
        freq: str = "D",
        **overrides,
    ) -> RechargeConfig:
        """RechargeConfig with a generated series (constant or sinusoidal)."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[
                RechargeSourceConfig(
                    source="synthetic",
                    start_date=start,
                    values=[float(values)] if isinstance(values, (int, float)) else list(values),
                    freq=freq,
                    **overrides,
                )
            ],
        )

    @classmethod
    def from_netcdf(
        cls,
        path: str | Path,
        *,
        start: str,
        end: str,
        source_unit: str | None = None,
        **overrides,
    ) -> RechargeConfig:
        """RechargeConfig reading a user NetCDF file as custom gridded source."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[
                RechargeSourceConfig(
                    source="custom",
                    path=Path(path),
                    source_unit=source_unit,
                    **overrides,
                )
            ],
        )

    @classmethod
    def from_geotiff(
        cls,
        path: str | Path,
        *,
        start: str,
        end: str,
        source_unit: str | None = None,
        **overrides,
    ) -> RechargeConfig:
        """RechargeConfig reading a user GeoTIFF as custom gridded source."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[
                RechargeSourceConfig(
                    source="custom",
                    path=Path(path),
                    source_unit=source_unit,
                    **overrides,
                )
            ],
        )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str,
        end: str,
        col_id: str = "id",
        col_x: str = "x",
        col_y: str = "y",
        col_datetime: str = "datetime",
        col_value: str = "value",
        **overrides,
    ) -> RechargeConfig:
        """RechargeConfig reading a directory of station CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[
                RechargeSourceConfig(
                    source="custom",
                    path=Path(path),
                    col_id=col_id,
                    col_x=col_x,
                    col_y=col_y,
                    col_datetime=col_datetime,
                    col_value=col_value,
                    **overrides,
                )
            ],
        )
