"""Pydantic configuration for ETP data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
    UrlSourceFieldsMixin,
    registered_section_source,
)


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
