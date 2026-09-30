"""Pydantic configuration for precipitation data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.managers.base_config import BaseVariableConfig
from hydromodpy.data.managers.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class PrecipitationSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one precipitation data source.

    Precipitation sources provide rainfall, snowfall, or total precipitation
    from custom files or SIM2 EDR products. Components select which
    precipitation signal is loaded from the provider.
    """

    source: Annotated[Literal["custom", "sim2", "explore2"], Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API, "
            "'explore2' for a local DRIAS Explore2 NetCDF (no network)."
        ),
    )

    # --- Precipitation-specific ---
    components: Annotated[list[Literal["liquid", "solid", "total"]], Profile.USER] = Field(
        default=["total"],
        min_length=1,
        description="Precipitation components: 'liquid' (rain), 'solid' (snow), 'total' (sum of both).",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="precipitation", category="data"),
    ] = Field(
        default=None,
        description=(
            "Directory containing location file and chronicle CSVs, or a single .nc/.tif file. "
            "For source = 'explore2', the local DRIAS Explore2 NetCDF to read."
        ),
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> PrecipitationSourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        if self.source == "explore2":
            if self.path is None:
                raise ValueError(
                    "Explore2 source requires 'path' (a local DRIAS Explore2 NetCDF file)."
                )
        return self


class PrecipitationConfig(BaseVariableConfig):
    """Top-level precipitation configuration.

    The section groups precipitation sources and an optional date window.
    Loaded data can drive hydrological forcing, recharge derivation, or
    diagnostic comparisons.
    """

    _TOML_SECTION = "precipitation"

    sources: Annotated[list[PrecipitationSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
