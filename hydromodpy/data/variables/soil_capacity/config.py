"""Pydantic configuration for the soil available water capacity (RU) raster."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile


class CustomSoilCapacitySource(HydroModelBase):
    """User-provided soil water capacity raster (GeoTIFF/ASC), values in mm."""

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' soil capacity provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="soil_capacity", category="data"),
    ] = Field(
        ...,
        description=(
            "Path to a raster of soil available water capacity in mm (GeoTIFF, ASC). "
            "Read only by [flow.sinks_sources.recharge.soil]."
        ),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS assumed for a raster that carries none of its own. Defaults to "
            "RGF93/Lambert-93 (EPSG:2154); set it to the site CRS for a non-French dataset."
        ),
    )


class SoilCapacityConfig(HydroModelBase):
    """Soil available water capacity raster, read by the soil reservoir.

    Example TOML::

        [[data.soil_capacity.sources]]
        source = "custom"
        path = "soil/ru_mm.tif"
    """

    sources: Annotated[list[CustomSoilCapacitySource], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Exactly one soil capacity raster. It spreads the ru of "
            "[flow.sinks_sources.recharge.soil] over classes inside each SAFRAN cell; "
            "ru stays the mean capacity of the cells."
        ),
    )
