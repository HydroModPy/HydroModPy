"""Pydantic configuration for crossings data sources.

A crossing is a structure laid across a channel: a road or a railway on an
embankment, a bridge, a weir, a dam. The DEM shows the embankment as a wall, so
the routing chain needs to know where they are to correct the ground. The
variable only says where; what to do with them is ``[geographic.crossings]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile

KINDS: tuple[str, ...] = ("road", "railway", "bridge", "weir", "dam", "other")
"""The values of the ``kind`` column, for every source."""


class CustomCrossingsSource(HydroModelBase):
    """User-provided crossings file (SHP/GPKG/GeoJSON).

    The file needs a ``kind`` column holding one of ``road``, ``railway``,
    ``bridge``, ``weir``, ``dam`` or ``other``. ``name`` and ``drop_m`` (the
    drop of a weir or a dam, in metres) are read when present.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' crossings provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="crossings", category="data"),
    ] = Field(
        ...,
        description=(
            "Path to a vector file (SHP, GPKG, GeoJSON) or to a folder holding one. "
            "It must carry a 'kind' column."
        ),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "Fallback CRS used only when the file carries none of its own. Defaults to "
            "RGF93/Lambert-93 (EPSG:2154)."
        ),
    )


class _ApiCrossingsSource(HydroModelBase):
    """Fields every downloading source shares."""

    page_size: Annotated[int, Profile.DEV] = Field(
        default=1000,
        ge=1,
        description="WFS pagination page size, in features.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Bypass the cache and download again.",
    )


class BdtopoCrossingsSource(_ApiCrossingsSource):
    """Roads and railways of the IGN BD TOPO, from the Geoplateforme WFS.

    A road segment flagged above the ground is a ``bridge`` and one flagged
    below it is ``other`` (a tunnel); ferries and stairs are left out.
    """

    source: Annotated[Literal["bdtopo"], Profile.USER] = Field(
        default="bdtopo",
        description="Discriminator tag selecting the BD TOPO roads and railways provider.",
    )


class RoeCrossingsSource(_ApiCrossingsSource):
    """Obstacles to flow of the Sandre ROE (dams, weirs, bridge sills), from the Sandre WFS.

    Only obstacles whose state is 'Existant' are kept.
    """

    source: Annotated[Literal["roe"], Profile.USER] = Field(
        default="roe",
        description="Discriminator tag selecting the ROE obstacles provider.",
    )


CrossingsSourceConfig: TypeAlias = Annotated[
    CustomCrossingsSource | BdtopoCrossingsSource | RoeCrossingsSource,
    Field(
        discriminator="source",
        description=(
            "Discriminated union of crossings data sources tagged by the 'source' provider key."
        ),
    ),
]


class CrossingsConfig(HydroModelBase):
    """Top-level crossings variable configuration.

    Example TOML::

        [[data.crossings.sources]]
        source = "bdtopo"

        [[data.crossings.sources]]
        source = "roe"

    ``mask_path`` sits here and not on a source because every source is asked
    over the same box.
    """

    sources: Annotated[list[CrossingsSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one crossings data source.",
    )
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "SHP/GPKG/GeoJSON/TIF whose bounds are the box the API sources are asked over. "
            "A project run has it filled in from the delineated watershed; a standalone "
            "call names it."
        ),
    )
