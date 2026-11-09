"""Pydantic configuration for water quality data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

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


class WaterQualitySourceConfig(
    TimeseriesColumnsMixin, TimeseriesSelectionMixin, SparseStationFallbackMixin
):
    """Configuration for one water quality data source.

    Water-quality sources load physico-chemical observations for river or
    piezometer sites. The source selects local files or Hub'Eau, optional
    parameter filters, station filters, and spatial discovery rules.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user files, or the id of a source registered for the "
            "water quality section, such as 'hubeau' for the Hub'Eau API."
        ),
    )

    @field_validator("source")
    @classmethod
    def _check_the_source_is_served_for_water_quality(cls, source: str) -> str:
        return registered_section_source(source, "water_quality")

    # --- Site type (river vs piezometer quality) ---
    site_type: Annotated[Literal["river", "piezometer"], Profile.USER] = Field(
        default="river",
        description="Type of site: 'river' (qualite_rivieres) or 'piezometer' (qualite_nappes).",
    )

    # --- Parameter filtering ---
    parameters: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description="Parameters to keep (e.g. ['pH', 'Nitrates']). None = all parameters.",
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="water_quality", category="data"),
    ] = Field(
        default=None,
        description="Directory containing location file and chronicle CSVs.",
        json_schema_extra=field_metadata(site_scoped=True),
    )

    # --- API nearest ---
    nearest: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep only the nearest station to the extent centroid.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> WaterQualitySourceConfig:
        if self.source in ("file", "custom"):
            if self.path is None:
                raise ValueError(
                    "File source requires 'path' (directory with location + chronicles)."
                )
        return self


class WaterQualityConfig(BaseVariableConfig):
    """Top-level water quality configuration.

    The section groups water-quality sources and an optional date window. It is
    designed for post-processing, model evaluation, and calibration workflows
    that compare simulated variables against observed chemistry.
    """

    _TOML_SECTION = "water_quality"

    sources: Annotated[list[WaterQualitySourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
