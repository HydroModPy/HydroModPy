"""Pydantic configuration for recharge data sources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
    UrlSourceFieldsMixin,
    registered_section_source,
)
from hydromodpy.model.forcing.recharge_estimators import ESTIMATORS, WEATHER_ESTIMATORS


class RechargeSourceConfig(UrlSourceFieldsMixin, TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one recharge data source.

    Recharge sources provide water input to the subsurface as custom files,
    SIM2 gridded products, or synthetic series. Synthetic fields can be
    constant, time-varying, or sinusoidal depending on the declared values and
    optional amplitude settings.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "runoff_ratio": (
            "no step ever read it, the recharge of a source is the water that "
            "reaches the saturated zone; give that net recharge in `values`"
        ),
    }

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user CSV files, or the id of a source registered "
            "for the recharge section, such as 'sim2' for the SIM2 EDR API and 'synthetic' "
            "for generated series."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_recharge(cls, source: str) -> str:
        return registered_section_source(source, "recharge")

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="recharge", category="data"),
    ] = Field(
        default=None,
        description="Folder of chronicle CSVs and their location file, one chronicle CSV read with the location file of its folder, or a single .nc/.tif file.",
        json_schema_extra=field_metadata(site_scoped=True),
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source unit for custom gridded .nc/.tif inputs. If omitted for NetCDF, units are inferred from variable metadata when available.",
    )

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
        json_schema_extra=field_metadata(site_scoped=True),
    )

    # --- Synthetic source fields ---
    values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Recharge values in mm/day. Single value for constant, list for time-varying.",
        json_schema_extra=field_metadata(unit="mm/day"),
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
        json_schema_extra=field_metadata(unit="-"),
    )
    amplitude: Annotated[float | None, Profile.EXPERT] = Field(
        default=None,
        description="Sinusoidal amplitude in mm/day (superimposed on values).",
        json_schema_extra=field_metadata(unit="mm/day"),
    )
    period_days: Annotated[int | None, Profile.EXPERT] = Field(
        default=None,
        description="Period of the sinusoid in days, whatever freq is. Each sample holds the mean of the wave over its own period.",
    )
    offset: Annotated[float | None, Profile.EXPERT] = Field(
        default=None,
        description="Added to the sinusoid, in mm/day. Requires amplitude and period_days.",
        json_schema_extra=field_metadata(unit="mm/day"),
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> RechargeSourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        if self.source == "explore2" and self.path is None:
            raise ValueError(
                "Explore2 source requires 'path' (a local DRIAS Explore2 NetCDF file of "
                "projected recharge)."
            )
        if self.source == "synthetic":
            if self.values is None:
                raise ValueError(
                    "Synthetic source requires 'values' (list of recharge values in mm/day)."
                )
        wave = {"amplitude": self.amplitude, "period_days": self.period_days}
        if self.source != "synthetic" and any(v is not None for v in wave.values()):
            raise ValueError("amplitude and period_days only shape a synthetic source.")
        if self.source != "synthetic" and self.offset is not None:
            raise ValueError("offset only shapes a synthetic source.")
        written = [name for name, value in wave.items() if value is not None]
        if len(written) == 1:
            missing = "period_days" if written[0] == "amplitude" else "amplitude"
            raise ValueError(
                f"{written[0]} draws a sinusoid only with {missing}: write both, or neither."
            )
        if self.offset is not None and not written:
            raise ValueError(
                f"offset = {self.offset} shifts the sinusoid, and this source declares none: "
                "write amplitude and period_days, or add the offset to values."
            )
        if self.period_days is not None and self.period_days <= 0:
            raise ValueError(f"period_days must be positive, got {self.period_days}.")
        return self


class RechargeConfig(BaseVariableConfig):
    """Top-level recharge configuration.

    The section groups recharge sources and an optional date window. Loaded
    recharge is used by groundwater and coupled flow workflows as a time-series
    or gridded forcing.
    """

    _TOML_SECTION = "recharge"

    sources: Annotated[list[RechargeSourceConfig], Profile.USER] = Field(
        default_factory=list,
        description="Data sources of the recharge. Write at least one, or a formula, not both.",
    )
    formula: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Compute a steady recharge from the yearly weather instead of loading a series: "
            "the formula runs on each complete calendar year of the run on the basin mean of "
            "[data.precipitation] (and of [data.temperature] for turc), and the run takes "
            "the mean over the years as its one rate. Only a run with [flow] flow_regime = "
            '"steady" reads it. "turc" gives an effective rainfall, which the run takes whole '
            "as recharge, so the drains do the share a RIPE would do. Guttman and Zuckerman "
            "and Kessler were fitted on karsts."
        ),
        json_schema_extra=field_metadata(
            value_docs={name: ESTIMATORS[name].reference for name in WEATHER_ESTIMATORS},
            stability="experimental",
        ),
        examples=["turc"],
    )

    @field_validator("formula")
    @classmethod
    def _formula_is_known(cls, formula: str | None) -> str | None:
        if formula is not None and formula not in WEATHER_ESTIMATORS:
            names = ", ".join(f'"{name}"' for name in WEATHER_ESTIMATORS)
            raise ValueError(
                f"formula = {formula!r} is not a yearly recharge formula: write one of {names}."
            )
        return formula

    @model_validator(mode="after")
    def _sources_or_formula(self) -> RechargeConfig:
        if bool(self.sources) == (self.formula is not None):
            raise ValueError(
                "[data.recharge] loads its recharge from sources or computes it with a "
                'formula: write [[data.recharge.sources]], or formula = "turc", one of the two.'
            )
        return self

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
