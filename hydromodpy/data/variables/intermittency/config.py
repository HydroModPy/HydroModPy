"""Pydantic configuration for intermittency (ONDE) data sources."""

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


class IntermittencySourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one intermittency data source.

    Intermittency sources load stream flow-state observations from local files
    or from the Hub'Eau ONDE API. The source can restrict stations by id,
    department code, project extent, or a spatial mask.
    """

    source: Annotated[Literal["custom", "hubeau"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau stream-flow API.",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="intermittency", category="data"),
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    code_departement: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description="INSEE department codes to filter Hub'Eau station discovery.",
    )
    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> IntermittencySourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        return self


class IntermittencyConfig(BaseVariableConfig):
    """Top-level intermittency configuration.

    The section groups flow-state observation sources and an optional date
    window. Loaded data can be used to compare simulated drying or active
    stream behavior against observed intermittency states.
    """

    _TOML_SECTION = "intermittency"

    sources: Annotated[list[IntermittencySourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
