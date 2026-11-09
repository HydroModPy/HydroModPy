"""Pydantic configuration for intermittency (ONDE) data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    SparseStationFallbackMixin,
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
    registered_section_source,
)


class IntermittencySourceConfig(
    TimeseriesColumnsMixin, TimeseriesSelectionMixin, SparseStationFallbackMixin
):
    """Configuration for one intermittency data source.

    Intermittency sources load stream flow-state observations from local files
    or from the Hub'Eau ONDE API. The source can restrict stations by id,
    department code, project extent, or a spatial mask.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user files, or the id of a source registered for the "
            "intermittency section, such as 'hubeau' for the Hub'Eau stream-flow API."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_intermittency(cls, source: str) -> str:
        return registered_section_source(source, "intermittency")

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="intermittency", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )

    # --- API source fields ---
    code_departement: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description="INSEE department codes to filter Hub'Eau station discovery.",
    )
    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> IntermittencySourceConfig:
        if self.source == "file":
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles)."
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
