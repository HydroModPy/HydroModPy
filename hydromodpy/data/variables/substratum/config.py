"""Pydantic configuration for substratum (aquifer-bottom) data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile


class CustomSubstratumSource(HydroModelBase):
    """User-provided substratum raster (GeoTIFF/ASC).

    The raster places the bottom of the aquifer. It is read only when
    ``[domain.depth_model] kind = "raster"``: ``domain.depth_model.quantity``
    then says whether its values are an elevation or a thickness below the
    top. Without that kind the raster is loaded but unused.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' substratum provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="substratum", category="geometry"),
    ] = Field(
        ...,
        description="Path to a custom substratum raster file (GeoTIFF, ASC).",
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "Fallback CRS used only when the raster carries none of its own. Defaults to "
            "RGF93/Lambert-93 (EPSG:2154); set it to the site CRS for a non-French dataset."
        ),
    )


class SubstratumConfig(HydroModelBase):
    """Top-level substratum variable configuration.

    Example TOML::

        [[data.substratum.sources]]
        source = "custom"
        path = "data/substratum/substratum_custom_bottom.tif"
    """

    sources: Annotated[list[CustomSubstratumSource], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description="Exactly one substratum data source: one bottom surface per model.",
    )

    @classmethod
    def from_raster(cls, path: str | Path, **overrides) -> SubstratumConfig:
        """SubstratumConfig from a custom substratum raster (GeoTIFF/ASC)."""
        return cls(sources=[CustomSubstratumSource(path=Path(path))], **overrides)
