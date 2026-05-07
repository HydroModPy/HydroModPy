"""Pydantic configuration for radiation data sources."""

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


class RadiationSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one radiation data source.

    Radiation sources load atmospheric and/or visible radiation from custom
    files or SIM2 EDR products. Components select the radiation signals used by
    downstream forcing and HELP coupling.
    """

    source: Annotated[Literal["custom", "sim2"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API.",
    )

    # --- Radiation-specific ---
    components: Annotated[list[Literal["atmospheric", "visible"]], Profile.USER] = Field(
        default=["atmospheric", "visible"],
        min_length=1,
        description="Radiation components: 'atmospheric' (DLI_Q) and/or 'visible' (SSI_Q).",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="radiation", category="data"),
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

    @model_validator(mode="after")
    def _check_source_requirements(self) -> RadiationSourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        return self


class RadiationConfig(BaseVariableConfig):
    """Top-level radiation configuration.

    The section groups radiation sources and an optional date window. Loaded
    data can support atmospheric forcing, potential evapotranspiration context,
    and HELP coupling.
    """

    _TOML_SECTION = "radiation"

    sources: Annotated[list[RadiationSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
