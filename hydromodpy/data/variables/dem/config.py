"""Pydantic configuration for DEM data sources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.catchment.administrative.regions import validate_french_regions
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.source.url import UrlSourceOptions
from hydromodpy.schema.job.inputset import InputState

BD_ALTI_RESOLUTION_M = 25.0
"""Pixel size of the BD ALTI that the department archives serve."""
RGE_ALTI_RESOLUTIONS_M = (1.0, 5.0)
"""Pixel sizes of the RGE ALTI that the WMS-Raster serves as the product itself."""


class _DemSourceBase(HydroModelBase):
    """Shared fields for DEM data sources."""

    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Vector polygon file (shp, gpkg or GeoJSON) whose extent this source is "
            "requested over. A project run fills it with the delineated watershed."
        ),
        json_schema_extra=field_metadata(site_scoped=True),
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Retrieve on the project extent rather than on this source's own filters. Only whether it is SET matters to the loaders; the two literals are not told apart, and a standard project run clips on the delineated watershed either way, through the mask the loader fills in. Declared at DEV level for that reason: a project run neither needs it nor changes with it."
        ),
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Download this source again instead of reading the cache.",
    )


class FileDemSource(_DemSourceBase):
    """User-provided raster file (GeoTIFF, Esri ASCII Grid, NetCDF)."""

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' DEM provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="dem", category="data"),
    ] = Field(
        ...,
        description="Path to user DEM file or directory (TIF, ASC, NC).",
        examples=["dem.tif"],
    )
    state: Annotated[InputState, Profile.USER] = Field(
        default="raw",
        description=(
            "Whether this DEM already drains. 'raw' lets the terrain chain "
            "condition it, 'conditioned' reads it as provided, so no engine "
            "conditions it and its file is the corrected DEM."
        ),
    )


class UrlDemSource(UrlSourceOptions, _DemSourceBase):
    """Remote DEM file, pinned by its sha256 when ``https`` is not used."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' DEM provider.",
    )
    state: Annotated[InputState, Profile.USER] = Field(
        default="raw",
        description=(
            "Whether this DEM already drains. 'raw' lets the terrain chain "
            "condition it, 'conditioned' reads it as provided, so no engine "
            "conditions it and its file is the corrected DEM."
        ),
    )


class BdAltiDemSource(_DemSourceBase):
    """IGN BD ALTI at 25 m, assembled from the department archives of the Geoplateforme."""

    source: Annotated[Literal["bdalti"], Profile.USER] = Field(
        default="bdalti",
        description="Discriminator tag selecting the IGN BD ALTI 25 m provider.",
    )
    departments: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Optional French department codes to fetch. When set, these codes "
            "constrain archive downloads instead of inferring departments only "
            "from the bbox."
        ),
    )
    country: Annotated[str, Profile.USER] = Field(
        default="FR",
        description="Country code used for administrative DEM selectors.",
    )
    regions: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=("Optional French administrative regions used to infer department downloads."),
    )
    file_format: Annotated[str, Profile.USER] = Field(
        default="ASC",
        description="Format of the archive requested from the IGN Geoplateforme, such as 'ASC'.",
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional CRS filter forwarded to Geoplateforme discovery.",
    )

    @model_validator(mode="after")
    def _check_french_regions(self) -> BdAltiDemSource:
        if str(self.country).upper() == "FR" and self.regions:
            object.__setattr__(self, "regions", validate_french_regions(self.regions))
        return self


class RgeAltiDemSource(_DemSourceBase):
    """IGN RGE ALTI at 1 m or 5 m, fetched by extent from the Geoplateforme WMS-Raster."""

    source: Annotated[Literal["rgealti"], Profile.USER] = Field(
        default="rgealti",
        description="Discriminator tag selecting the IGN RGE ALTI provider.",
    )
    resolution_m: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description=(
            "DEM pixel size in metres, 1 or 5, 5 when unset, the size the WMS-Raster "
            "serves. It comes "
            "first of three: geographic.catchment.dem_resolution aggregates this pixel, and "
            "mesh.cell_size defaults to the result. The 1 m grid is native and, inland, a "
            "5 m request returns its centre pixels unchanged, while the server resamples "
            "any other size with an undocumented kernel. A request above 150 million "
            "pixels is refused (a 1 m box is limited to about 12 km a side), so 1 m cannot "
            "bootstrap a project from its outlet: declare the DEM as a [[data.dem.sources]] "
            'row with source = "file", or use 5 m.'
        ),
        json_schema_extra={"unit": "m"},
    )

    @model_validator(mode="after")
    def _check_resolution(self) -> RgeAltiDemSource:
        if self.resolution_m not in (None, *RGE_ALTI_RESOLUTIONS_M):
            raise ValueError("source 'rgealti' is served at 1 m or 5 m only.")
        return self


DemSourceConfig: TypeAlias = Annotated[
    FileDemSource | UrlDemSource | BdAltiDemSource | RgeAltiDemSource,
    Field(
        discriminator="source",
        description=(
            "Discriminated union of DEM data sources tagged by the 'source' provider key. "
            "Use 'file' for a user file (TIF/ASC/NC), 'url' for a remote file, 'bdalti' "
            "for the IGN BD ALTI at 25 m and 'rgealti' for the IGN RGE ALTI at 1 m or 5 m."
        ),
    ),
]

RETIRED_DEM_SOURCES: dict[str, str] = {
    "ign_geoplateforme_dem": (
        'source = "ign_geoplateforme_dem" is not accepted any more. Write source = '
        '"bdalti" for the 25 m BD ALTI, or source = "rgealti" with resolution_m = 5 or 1 '
        "for the RGE ALTI, and delete dataset."
    ),
}
"""Each retired DEM source tag, with the sentence that names what replaces it."""


class DemConfig(HydroModelBase):
    """Top-level DEM variable configuration.

    The section declares one or more elevation sources. The loaded DEM can feed
    geographic preprocessing directly or be cached as a reusable data product.

    Example TOML::

        [data.dem]

        [[data.dem.sources]]
        source = "bdalti"
        regions = ["Bretagne"]

        [[data.dem.sources]]
        source = "rgealti"
        resolution_m = 5.0

        [[data.dem.sources]]
        source = "file"
        path = "data/my_dem.tif"
    """

    sources: Annotated[list[DemSourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one DEM data source.",
    )

    @classmethod
    def from_geotiff(cls, path: str | Path, **overrides) -> DemConfig:
        """DemConfig reading a user GeoTIFF (or ASC/NC) file."""
        return cls(sources=[FileDemSource(path=Path(path), **overrides)])

    @field_validator("sources", mode="before")
    @classmethod
    def _name_the_replacement_of_a_retired_source(cls, value: Any) -> Any:
        """Refuse a retired source tag with what replaces it."""
        for row in value if isinstance(value, list) else ():
            tag = row.get("source") if isinstance(row, Mapping) else None
            if isinstance(tag, str) and tag in RETIRED_DEM_SOURCES:
                raise ValueError(RETIRED_DEM_SOURCES[tag])
        return value

    @classmethod
    def bdalti(cls, **overrides) -> DemConfig:
        """DemConfig pulling the IGN BD ALTI at 25 m."""
        return cls(sources=[BdAltiDemSource(**overrides)])

    @classmethod
    def rgealti(cls, **overrides) -> DemConfig:
        """DemConfig pulling the IGN RGE ALTI at 1 m or 5 m."""
        return cls(sources=[RgeAltiDemSource(**overrides)])
