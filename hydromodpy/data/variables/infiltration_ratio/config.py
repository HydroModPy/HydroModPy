"""The ``[data.infiltration_ratio]`` section: one source of the ratio, 0 to 1 per pixel."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.common.clients.ocsge import SEALED_COVERS
from hydromodpy.data.source.url import UrlSourceOptions

COVER_KEY = re.compile(r"^CS(\d+(\.\d+)*)?$")
"""A key of the table of ratios: an OCS GE cover code or the start of one, such as CS2.1."""


class FileInfiltrationRatioSource(HydroModelBase):
    """User-provided raster of the infiltration ratio (GeoTIFF/ASC), 0 to 1 per pixel."""

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' infiltration ratio provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="infiltration_ratio", category="data"),
    ] = Field(
        ...,
        description=(
            "Path to a raster of the share of the soil excess that reaches the aquifer, "
            "0 to 1 per pixel (GeoTIFF, ASC). Read only by [flow.sinks_sources.recharge.soil]."
        ),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class UrlInfiltrationRatioSource(UrlSourceOptions, HydroModelBase):
    """Remote raster of the infiltration ratio, downloaded into the data cache by ``url``."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' infiltration ratio provider.",
    )


class OcsgeInfiltrationRatioSource(HydroModelBase):
    """OCS GE of the IGN, each cover given the ratio the section writes for it, 10 m."""

    source: Annotated[Literal["ocsge"], Profile.USER] = Field(
        default="ocsge",
        description="Discriminator tag selecting the IGN OCS GE provider.",
    )
    year: Annotated[int, Profile.USER] = Field(
        ...,
        ge=2000,
        le=2100,
        description=(
            "Latest edition read in each department, up to this year. Written down so "
            "that a new edition of the IGN does not move a run."
        ),
        json_schema_extra=field_metadata(unit="year"),
        examples=[2023],
    )
    ratios: Annotated[dict[str, float], Profile.USER] = Field(
        ...,
        min_length=1,
        description=(
            "Infiltration ratio, 0 to 1, of each OCS GE cover, keyed by its code or the "
            'start of one: "CS2.1" holds for every woody cover, and the longest key that '
            'starts a code wins. "CS" alone gives every cover left. HydroModPy ships no '
            "value: the ratios belong to the site and to the study that sets them. The "
            "sealed covers CS1.1.1.1 and CS1.1.1.2 are left out of the map, since "
            "[data.impervious] runs them off whole. A cover of the area that no key "
            "starts is refused, with its share of the area."
        ),
        examples=[{"CS2.1": 0.8, "CS2.2": 0.6, "CS": 0.5}],
    )
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

    @field_validator("ratios")
    @classmethod
    def _ratios_name_covers_between_0_and_1(cls, ratios: dict[str, float]) -> dict[str, float]:
        bad_keys = [key for key in ratios if not COVER_KEY.match(key)]
        if bad_keys:
            raise ValueError(
                f"ratios names {bad_keys}, which start no OCS GE cover code: write keys "
                'such as "CS2.1.1.1", "CS2.2" or "CS".'
            )
        sealed = [key for key in ratios if key.startswith("CS1.1.1")]
        if sealed:
            raise ValueError(
                f"ratios names {sealed}, which hold only the sealed covers {list(SEALED_COVERS)}: "
                "they are left out of this map and run off whole through [data.impervious]."
            )
        outside = {key: value for key, value in ratios.items() if not 0.0 <= value <= 1.0}
        if outside:
            raise ValueError(f"ratios {outside} leave 0 to 1: a ratio is a share.")
        return ratios


InfiltrationRatioSourceConfig: TypeAlias = Annotated[
    FileInfiltrationRatioSource | UrlInfiltrationRatioSource | OcsgeInfiltrationRatioSource,
    Field(discriminator="source", description="One source of the infiltration ratio."),
]


class InfiltrationRatioConfig(HydroModelBase):
    """Infiltration ratio of the soil excess, read by the soil reservoir cell by cell.

    Example TOML::

        [[data.infiltration_ratio.sources]]
        source = "ocsge"
        year = 2023
        ratios = { "CS2.1" = 0.8, "CS2.2" = 0.6, "CS" = 0.5 }
    """

    sources: Annotated[list[InfiltrationRatioSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Exactly one source of the infiltration ratio. Each soil column takes the mean "
            "ratio of its SAFRAN cell inside the catchment, in place of infiltration_ratio."
        ),
    )


__all__ = [
    "FileInfiltrationRatioSource",
    "InfiltrationRatioConfig",
    "OcsgeInfiltrationRatioSource",
    "UrlInfiltrationRatioSource",
]
