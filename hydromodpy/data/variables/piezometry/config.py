"""Pydantic configuration for piezometry data sources."""

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


class PiezometrySourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Configuration for one piezometry data source.

    Piezometry sources load groundwater-level or depth observations from local
    station files or from the Hub'Eau piezometry API. Station filters, nearest
    station selection, and source units are declared here.
    """

    source: Annotated[Literal["custom", "hubeau"], Profile.USER] = Field(
        ..., description="Data provider."
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="piezometry", category="data"),
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Annotated[Literal["level", "depth"] | None, Profile.USER] = Field(
        default=None, description="Hub'Eau measurement type: 'level' or 'depth'."
    )
    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    nearest: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep only the nearest piezometer to the extent centroid.",
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> PiezometrySourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        if self.source == "hubeau":
            if self.product is None:
                raise ValueError("Hub'Eau source requires 'product' ('level' or 'depth').")
        return self


class PiezometryConfig(BaseVariableConfig):
    """Top-level piezometry configuration.

    The section groups groundwater observation sources and an optional date
    window. Loaded piezometric series can support calibration targets,
    diagnostics, and hydrogeological context.
    """

    _TOML_SECTION = "piezometry"

    sources: Annotated[list[PiezometrySourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )
