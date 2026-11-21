"""The ``[data.curve_number]`` section: a curve number raster, or one built from land cover.

A ``file`` or ``url`` source is a curve number map, such as GCN250. The other three build
one: they read a land cover (a raster of a named legend, WorldCover, or OCS GE), send each
class to the ESA CCI pivot of ``data/common/land_cover.py``, and read the GCN250 curve
number of that class on the hydrologic soil group the section gives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.common.land_cover import CCI_CLASSES, LEFT_OUT, SOIL_GROUPS
from hydromodpy.data.source.url import UrlSourceOptions


class FileCurveNumberSource(HydroModelBase):
    """User-provided raster of the SCS curve number (GeoTIFF/ASC), AMC II, such as GCN250."""

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' curve number provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="curve_number", category="data"),
    ] = Field(
        ...,
        description=(
            "Path to a raster of the SCS curve number under average moisture (AMC II), "
            "for instance the GCN250 map of Jaafar et al. (2019) (GeoTIFF, ASC). Read "
            "only by [flow.sinks_sources.recharge.soil]."
        ),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class UrlCurveNumberSource(UrlSourceOptions, HydroModelBase):
    """Remote curve number raster, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' curve number provider.",
    )


class _FromLandCover(HydroModelBase):
    """What every source that builds the curve number from land cover reads."""

    hsg: Annotated[Literal["A", "B", "C", "D"] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Hydrologic soil group of the whole area, A (low runoff potential) to D (high). "
            "Write it, or hsg_path, never both: HydroModPy picks no soil group for a site."
        ),
    )
    hsg_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="curve_number", category="data"),
    ] = Field(
        default=None,
        description=(
            "Raster of the hydrologic soil group coded as HYSOGs250m (Ross et al. 2018, "
            "ORNL DAAC 1566): 1 to 4 for A to D, 11 to 14 for the wet groups A/D to D/D, "
            "read as D like GCN250 does. Any other value is no data."
        ),
    )
    classes: Annotated[dict[str, int], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Classes of the land cover sent to another ESA CCI class than the shipped "
            'crosswalk, keyed by their code, such as { "30" = 11 } to read WorldCover '
            "grassland as managed meadow. 0 leaves a class out of the map. A class of the "
            "area that neither the crosswalk nor this table names is refused."
        ),
        examples=[{"30": 11}],
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

    @field_validator("classes")
    @classmethod
    def _classes_point_to_the_pivot(cls, classes: dict[str, int]) -> dict[str, int]:
        unknown = {k: v for k, v in classes.items() if v != LEFT_OUT and v not in CCI_CLASSES}
        if unknown:
            raise ValueError(
                f"classes sends {unknown} to no ESA CCI class: write a code of the CCI "
                "legend, such as 10, 11, 60 or 130, or 0 to leave the class out."
            )
        return classes

    @model_validator(mode="after")
    def _one_soil_group(self) -> _FromLandCover:
        if (self.hsg is None) == (self.hsg_path is None):
            raise ValueError(
                "The curve number of a land cover depends on the hydrologic soil group: "
                f"write hsg, one of {', '.join(SOIL_GROUPS)}, or hsg_path, one of the two."
            )
        return self


class LandCoverCurveNumberSource(_FromLandCover):
    """A land cover raster of a named legend, turned into the curve number."""

    source: Annotated[Literal["land_cover"], Profile.USER] = Field(
        default="land_cover",
        description="Discriminator tag selecting a land cover raster.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="curve_number", category="data"),
    ] = Field(
        ...,
        description="Path to a land cover raster, one class code per pixel (GeoTIFF, ASC).",
    )
    nomenclature: Annotated[Literal["cci", "worldcover", "clc", "custom"], Profile.USER] = Field(
        ...,
        description=(
            'Legend of the raster: "cci" (ESA CCI LC), "worldcover" (ESA WorldCover), '
            '"clc" (Corine Land Cover level 3, such as 211), or "custom" for any other '
            "legend, whose every class classes then sends to an ESA CCI class."
        ),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class WorldcoverCurveNumberSource(_FromLandCover):
    """ESA WorldCover, its classes sent to the ESA CCI pivot, 10 m over the world."""

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


class OcsgeCurveNumberSource(_FromLandCover):
    """OCS GE of the IGN, its covers sent to the ESA CCI pivot, 10 m, France."""

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


CurveNumberSourceConfig: TypeAlias = Annotated[
    FileCurveNumberSource
    | UrlCurveNumberSource
    | LandCoverCurveNumberSource
    | WorldcoverCurveNumberSource
    | OcsgeCurveNumberSource,
    Field(discriminator="source", description="One source of the curve number."),
]


class CurveNumberConfig(HydroModelBase):
    """SCS curve number raster, read by the soil reservoir.

    Example TOML::

        [[data.curve_number.sources]]
        source = "ocsge"
        year = 2023
        hsg = "C"
    """

    sources: Annotated[list[CurveNumberSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Exactly one curve number source. Each soil column takes the mean curve number "
            "of its SAFRAN cell inside the catchment, in place of curve_number. A source "
            "built from land cover leaves the sealed and built-up classes out, since "
            "[data.impervious] runs them off whole, and leaves water and snow out, which "
            "GCN250 gives no curve number."
        ),
    )


__all__ = [
    "CurveNumberConfig",
    "FileCurveNumberSource",
    "LandCoverCurveNumberSource",
    "OcsgeCurveNumberSource",
    "UrlCurveNumberSource",
    "WorldcoverCurveNumberSource",
]
