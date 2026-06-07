"""Pydantic configuration for hydrography data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile


class HydrographySourceConfig(HydroModelBase):
    """Configuration for one hydrography data source.

    Hydrography sources describe river-network vector or raster data. Use
    ``custom`` for local files, ``osm`` for OpenStreetMap waterways,
    ``bdtopage`` for the Sandre WFS service, or ``euhydro`` for the EEA
    EU-Hydro service.
    """

    source: Annotated[Literal["custom", "osm", "bdtopage", "euhydro"], Profile.USER] = Field(
        ..., description="Data provider."
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="hydrography", category="data"),
    ] = Field(
        default=None,
        description="Path to a vector file (SHP/GPKG/GeoJSON), raster (TIF/TIFF), or directory containing one.",
    )
    rasterize_field: Annotated[str, Profile.USER] = Field(
        default="FID",
        description="Attribute field used when rasterising the vector layer.",
    )

    # --- BD Topage (Sandre WFS) ---
    typename: Annotated[str, Profile.DEV] = Field(
        default="sa:CoursEau_FXX_Topage2025",
        description="WFS typename for BD Topage.",
    )
    page_size: Annotated[int, Profile.DEV] = Field(
        default=2000,
        description="WFS pagination page size (BD Topage).",
    )

    # --- EU-Hydro (EEA REST) ---
    group_name: Annotated[str, Profile.DEV] = Field(
        default="River_Net_lines",
        description="MapServer group name for EU-Hydro layer discovery.",
    )
    euhydro_page_size: Annotated[int, Profile.DEV] = Field(
        default=1000,
        description="Pagination page size for EU-Hydro REST queries.",
    )

    # --- Cache ---
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Bypass API cache and re-download data.",
    )

    # --- OSM ---
    waterway_types: Annotated[list[str], Profile.DEV] = Field(
        default_factory=lambda: ["river", "stream"],
        description="OSM waterway tag values to fetch.",
    )

    @model_validator(mode="after")
    def _check_custom_requires_path(self) -> HydrographySourceConfig:
        if self.source == "custom" and self.path is None:
            raise ValueError("Custom source requires 'path'.")
        return self


class HydrographyConfig(HydroModelBase):
    """Top-level hydrography configuration.

    The section lists stream-network sources used by data loading and boundary
    preparation. It is commonly inferred when ``flow.active_bc`` contains a
    stream boundary condition.
    """

    sources: Annotated[list[HydrographySourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one hydrography data source.",
    )
