"""Pydantic configuration for wind data sources."""

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


class WindSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one wind-speed data source.

    Wind sources load station or gridded wind-speed time series from custom
    files or SIM2 EDR products. Source-level fields define file paths, station
    columns, masks, units, and cache refresh behavior.
    """

    source: Annotated[Literal["custom", "sim2"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API.",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="wind", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> WindSourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        return self


class WindConfig(BaseVariableConfig):
    """Top-level wind-speed configuration.

    The section groups wind sources and an optional date window. Loaded data can
    support atmospheric forcing, evapotranspiration context, and HELP coupling.
    """

    _TOML_SECTION = "wind"

    sources: Annotated[list[WindSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
