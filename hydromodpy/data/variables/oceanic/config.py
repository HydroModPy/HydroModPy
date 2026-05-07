"""Pydantic configuration for oceanic data sources."""

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


class OceanicSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one oceanic boundary data source.

    Oceanic sources describe sea-level information for coastal boundary
    conditions. Use ``custom`` for local files, ``shom`` for tide-gauge data,
    or ``constant`` for a fixed mean sea-level value.
    """

    source: Annotated[Literal["custom", "shom", "constant"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user CSV/NC/TIF files, 'shom' for SHOM API, 'constant' for fixed MSL.",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="oceanic", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs, or a single .nc/.tif file.",
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source unit for custom gridded .nc/.tif inputs. If omitted for NetCDF, units are inferred from variable metadata when available.",
    )

    # --- Constant source fields ---
    value: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Constant mean sea-level value in metres.",
    )

    # --- SHOM API fields ---
    nearest: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Use nearest tide gauge to watershed centroid.",
    )
    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Maximum search radius (km) for nearest tide gauge.",
    )
    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Raise if SHOM returns no observations.",
    )

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations or clip grid.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> OceanicSourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
                )
        if self.source == "constant":
            if self.value is None:
                raise ValueError("Constant source requires 'value' (mean sea-level in metres).")
        return self


class OceanicConfig(BaseVariableConfig):
    """Top-level oceanic configuration.

    The section groups sea-level sources and an optional date window. It is
    commonly inferred when ``flow.active_bc`` contains an ocean boundary
    condition.
    """

    _TOML_SECTION = "oceanic"

    sources: Annotated[list[OceanicSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one data source.",
    )
