"""Pydantic configuration for substratum (aquifer-bottom) data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.source.url import UrlSourceOptions


class FileSubstratumSource(HydroModelBase):
    """User-provided substratum raster (GeoTIFF/ASC).

    The raster places the bottom of the aquifer. It is read only when
    ``[domain.depth_model] kind`` is ``"raster_substratum"`` (its values are the
    elevation of the substratum) or ``"raster_thickness"`` (its values are the
    aquifer thickness below the top). With any other kind it is loaded but unused.
    """

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' substratum provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="substratum", category="geometry"),
    ] = Field(
        ...,
        description="Path to a user substratum raster file (GeoTIFF, ASC).",
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class UrlSubstratumSource(UrlSourceOptions, HydroModelBase):
    """Remote substratum raster, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' substratum provider.",
    )

    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class SubstratumConfig(HydroModelBase):
    """Top-level substratum variable configuration.

    Example TOML::

        [[data.substratum.sources]]
        source = "file"
        path = "data/substratum/substratum_file_bottom.tif"
    """

    sources: Annotated[list[FileSubstratumSource | UrlSubstratumSource], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description="Exactly one substratum data source: one bottom surface per model.",
    )

    @classmethod
    def from_raster(cls, path: str | Path, **overrides) -> SubstratumConfig:
        """SubstratumConfig from a user substratum raster (GeoTIFF/ASC)."""
        return cls(sources=[FileSubstratumSource(path=Path(path))], **overrides)
