"""Pydantic configuration for recharge data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.base_config import BaseVariableConfig
from hydromodpy.data.variables.timeseries_variable_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class RechargeSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one recharge data source.

    Recharge sources provide water input to the subsurface as custom files,
    SIM2 gridded products, or synthetic series. Synthetic fields can be
    constant, time-varying, or sinusoidal depending on the declared values and
    optional amplitude settings.
    """

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
    """Top-level recharge configuration.

    The section groups recharge sources and an optional date window. Loaded
    recharge is used by groundwater and coupled flow workflows as a time-series
    or gridded forcing.
    """

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
