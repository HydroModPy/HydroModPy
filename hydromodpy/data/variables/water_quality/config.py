"""Pydantic configuration for water quality data sources."""

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


class WaterQualitySourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one water quality data source.

    Water-quality sources load physico-chemical observations for river or
    piezometer sites. The source selects local files or Hub'Eau, optional
    parameter filters, station filters, and spatial discovery rules.
    """

    source: Annotated[Literal["custom", "hubeau"], Profile.USER] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

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
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API fallback / nearest ---
    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )
    nearest: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep only the nearest station to the extent centroid.",
    )

    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> WaterQualitySourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
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
