"""Radiation, ETP and precipitation, the atmospheric forcing series variables.

Each one reads series from the user's files, from the SIM2 EDR products, and for
ETP and precipitation from a local Explore2 NetCDF. The source is a string checked
against the sources registered for the section.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.grids import GridVariable
from hydromodpy.data.families.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
    UrlSourceFieldsMixin,
    registered_section_source,
)

# --- Radiation -------------------------------------------------------------


class RadiationSourceConfig(UrlSourceFieldsMixin, TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one radiation data source.

    Radiation sources load atmospheric and/or visible radiation from custom
    files or SIM2 EDR products. Components select the radiation signals used by
    downstream forcing and HELP coupling.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user CSV files, or the id of a source registered "
            "for the radiation section, such as 'sim2' for the SIM2 EDR API."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_radiation(cls, source: str) -> str:
        return registered_section_source(source, "radiation")

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
        json_schema_extra=field_metadata(site_scoped=True),
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> RadiationSourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
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


class RadiationVariable(GridVariable):
    VARIABLE_NAME = "radiation"
    INTERNAL_UNIT = "MJ/m2/j"


# --- Potential evapotranspiration ------------------------------------------


class EtpSourceConfig(UrlSourceFieldsMixin, TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one potential evapotranspiration data source.

    ETP sources load potential evapotranspiration from custom files or SIM2
    EDR products. Source-level fields define station columns, gridded file
    paths, masks, units, and cache refresh behavior.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user CSV files, or the id of a source registered "
            "for the ETP section, such as 'sim2' for the SIM2 EDR API and 'explore2' for a "
            "local DRIAS Explore2 NetCDF (no network)."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_etp(cls, source: str) -> str:
        return registered_section_source(source, "etp")

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="etp", category="data"),
    ] = Field(
        default=None,
        description=(
            "Directory containing location file and chronicle CSVs, or a single .nc/.tif file. "
            "For source = 'explore2', the local DRIAS Explore2 NetCDF to read."
        ),
        json_schema_extra=field_metadata(site_scoped=True),
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional CRS fallback for custom gridded NetCDF inputs that do not declare CRS metadata.",
    )
    nodata: Annotated[float | int | str | None, Profile.USER] = Field(
        default=None,
        description="Optional nodata fallback for custom gridded NetCDF inputs that do not declare nodata metadata.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> EtpSourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        if self.source == "explore2":
            if self.path is None:
                raise ValueError(
                    "Explore2 source requires 'path' (a local DRIAS Explore2 NetCDF file)."
                )
        return self


class EtpConfig(BaseVariableConfig):
    """Top-level potential evapotranspiration configuration.

    The section groups ETP sources and an optional date window. Loaded data can
    be used by land-surface coupling, recharge estimation, or atmospheric
    forcing workflows.
    """

    _TOML_SECTION = "etp"

    sources: Annotated[list[EtpSourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )


class EtpVariable(GridVariable):
    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"


# --- Precipitation ---------------------------------------------------------


class PrecipitationSourceConfig(
    UrlSourceFieldsMixin, TimeseriesColumnsMixin, TimeseriesSelectionMixin
):
    """Configuration for one precipitation data source.

    Precipitation sources provide rainfall, snowfall, or total precipitation
    from custom files or SIM2 EDR products. Components select which
    precipitation signal is loaded from the provider.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user CSV files, or the id of a source registered "
            "for the precipitation section, such as 'sim2' for the SIM2 EDR API and "
            "'explore2' for a local DRIAS Explore2 NetCDF (no network)."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_precipitation(cls, source: str) -> str:
        return registered_section_source(source, "precipitation")

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
        json_schema_extra=field_metadata(site_scoped=True),
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> PrecipitationSourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
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


class PrecipitationVariable(GridVariable):
    VARIABLE_NAME = "precipitation"
    INTERNAL_UNIT = "mm/day"
