"""The ``[data.impervious]`` section: one source of the sealed share, 0 to 1 per pixel."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.source.url import UrlSourceOptions


class _ProviderSource(HydroModelBase):
    """What a provider source of the sealed share is asked over."""

    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Vector polygon file (shp, gpkg or GeoJSON) whose extent this source is "
            "requested over. A project run fills it with the delineated watershed."
        ),
        json_schema_extra=field_metadata(site_scoped=True),
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Build the map again instead of reading the cache.",
    )


class FileImperviousSource(HydroModelBase):
    """User-provided raster of the sealed share (GeoTIFF/ASC), 0 to 1 per pixel."""

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' impervious provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="impervious", category="data"),
    ] = Field(
        ...,
        description=(
            "Path to a raster of the sealed share of each pixel, 0 to 1 (GeoTIFF, ASC). "
            "Read only by [flow.sinks_sources.recharge.soil]."
        ),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class UrlImperviousSource(UrlSourceOptions, HydroModelBase):
    """Remote raster of the sealed share, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' impervious provider.",
    )


class OcsgeImperviousSource(_ProviderSource):
    """OCS GE of the IGN, its built and unbuilt sealed covers rasterized at 10 m."""

    source: Annotated[Literal["ocsge"], Profile.USER] = Field(
        default="ocsge",
        description="Discriminator tag selecting the IGN OCS GE provider.",
    )
    year: Annotated[int, Profile.USER] = Field(
        ...,
        ge=2000,
        le=2100,
        description=(
            "Latest edition read in each department, up to this year: 2023 reads the 2023 "
            "edition of Ille-et-Vilaine and the 2021 one of a department without 2023. "
            "Written down so that a new edition of the IGN does not move a run."
        ),
        json_schema_extra=field_metadata(unit="year"),
        examples=[2023],
    )


class WorldcoverImperviousSource(_ProviderSource):
    """ESA WorldCover, its built-up class read as sealed, 10 m over the world."""

    source: Annotated[Literal["worldcover"], Profile.USER] = Field(
        default="worldcover",
        description="Discriminator tag selecting the ESA WorldCover provider.",
    )
    year: Annotated[Literal[2020, 2021], Profile.USER] = Field(
        default=2021,
        description=(
            "Map read: 2020 (algorithm v100) or 2021 (v200). The two differ by their "
            "algorithm as much as by the ground, so a change between them is no trend."
        ),
        json_schema_extra=field_metadata(unit="year"),
    )


ImperviousSourceConfig: TypeAlias = Annotated[
    FileImperviousSource | UrlImperviousSource | OcsgeImperviousSource | WorldcoverImperviousSource,
    Field(discriminator="source", description="One source of the sealed share."),
]


class ImperviousConfig(HydroModelBase):
    """Sealed share of the ground, read by the soil reservoir as its impervious fraction.

    Example TOML::

        [[data.impervious.sources]]
        source = "ocsge"
        year = 2023
    """

    sources: Annotated[list[ImperviousSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Exactly one source of the sealed share. Each soil column takes the mean "
            "share of its SAFRAN cell inside the catchment, in place of impervious_fraction."
        ),
    )


__all__ = [
    "FileImperviousSource",
    "ImperviousConfig",
    "OcsgeImperviousSource",
    "UrlImperviousSource",
    "WorldcoverImperviousSource",
]
