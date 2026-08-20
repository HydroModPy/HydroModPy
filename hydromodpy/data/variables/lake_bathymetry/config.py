"""Pydantic configuration for lake bathymetry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.core.tracking import InputFile


class CustomLakeBathymetrySource(HydroModelBase):
    """User-provided lake bathymetry raster (GeoTIFF/ASC).

    The bathymetry raster fixes the lake-bed elevation per cell - i.e. where
    and at what depth the lake exchanges with the aquifer (the LAK interface).
    It is consumed only when a lake enables
    ``flow.sinks_sources.lakes.<id>.bed_reconstruction``: the raster is then
    resampled onto the lake cells, reconciled to the abacus, and carved into
    ``top``/``botm`` so the bed follows the real basin. Without that flag the
    raster is loaded but unused (the abacus alone drives the stage-storage
    relation).
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' lake-bathymetry provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="lake_bathymetry", category="data"),
    ] = Field(
        ...,
        description="Path to a custom lake-bathymetry raster file (GeoTIFF, ASC).",
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "Fallback CRS used only when the raster carries none of its own. Defaults to "
            "RGF93/Lambert-93 (EPSG:2154); set it to the site CRS for a non-French dataset."
        ),
    )


class LakeBathymetryConfig(HydroModelBase):
    """Top-level lake-bathymetry variable configuration.

    Example TOML::

        [[data.lake_bathymetry.sources]]
        source = "custom"
        path = "data/lake_bathymetry/lake_bathymetry_custom_lac0.tif"
    """

    sources: Annotated[list[CustomLakeBathymetrySource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one lake-bathymetry data source.",
    )
    id: Annotated[IdentifierStr, Profile.USER] = Field(
        default="lake_bathymetry",
        description="Identifier of the lake-bathymetry spatial field.",
    )

    @classmethod
    def from_raster(cls, path: str | Path, **overrides) -> LakeBathymetryConfig:
        """LakeBathymetryConfig from a custom bathymetry raster (GeoTIFF/ASC)."""
        return cls(sources=[CustomLakeBathymetrySource(path=Path(path))], **overrides)
