"""Pydantic configuration for DEM data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from hydromodpy.core.administrative_france import validate_french_regions
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile

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
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Retrieve on the project extent rather than on this source's own filters. Only whether it is SET matters to the loaders; the two literals are told apart by the site-selection pipeline alone, and a standard project run clips on the delineated watershed either way, through the mask the loader fills in. Declared at DEV level for that reason: a project run neither needs it nor changes with it."
        ),
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Download this source again instead of reading the cache.",
    )


class CustomDemSource(_DemSourceBase):
    """User-provided raster file (GeoTIFF, Esri ASCII Grid, NetCDF)."""

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' DEM provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="dem", category="data"),
    ] = Field(
        ...,
        description="Path to custom DEM file or directory (TIF, ASC, NC).",
        examples=["dem.tif"],
    )


class _FrenchAdministrativeDemSource(_DemSourceBase):
    """Shared French administrative selectors for IGN DEM sources."""

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

    @model_validator(mode="after")
    def _check_french_regions(self) -> _FrenchAdministrativeDemSource:
        if str(self.country).upper() == "FR" and self.regions:
            object.__setattr__(self, "regions", validate_french_regions(self.regions))
        return self


class IgnGeoplateformeDemSource(_FrenchAdministrativeDemSource):
    """Recommended IGN DEM source: BD ALTI from archives, RGE ALTI from WMS-Raster."""

    source: Annotated[Literal["ign_geoplateforme_dem"], Profile.USER] = Field(
        default="ign_geoplateforme_dem",
        description="Discriminator tag selecting the IGN Geoplateforme DEM provider.",
    )
    dataset: Annotated[Literal["bd-alti", "rge-alti"], Profile.USER] = Field(
        default="bd-alti",
        description=(
            "IGN DEM product assembled by the data manager. 'bd-alti' is the 25 m "
            "BD ALTI built from the department archives. 'rge-alti' is the RGE ALTI "
            "built from Geoplateforme WMS-Raster tiles, 5 m by default, 1 m allowed."
        ),
    )
    resolution_m: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description=(
            "DEM pixel size in metres. 'bd-alti' accepts 25 only and defaults to it. "
            "'rge-alti' accepts 1 or 5 and defaults to 5: the 1 m grid is native and, "
            "inland, a 5 m request returns its centre pixels unchanged, while the server "
            "resamples any other size with an undocumented kernel. A request above 150 "
            "million pixels is refused (a 1 m box is limited to about 12 km a side), so 1 m "
            "cannot bootstrap a project from its outlet: give dem_init_path a file or use 5 m."
        ),
    )
    file_format: Annotated[str, Profile.USER] = Field(
        default="ASC",
        description=(
            "Format of the archive requested from the IGN Geoplateforme, such as 'ASC'. "
            "Not used by 'rge-alti', which is a GeoTIFF."
        ),
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional CRS filter forwarded to Geoplateforme discovery. "
            "Not used by 'rge-alti', which is requested in EPSG:2154."
        ),
    )

    @model_validator(mode="after")
    def _check_dataset_options(self) -> IgnGeoplateformeDemSource:
        if self.dataset == "bd-alti":
            if self.resolution_m not in (None, 25.0):
                raise ValueError("dataset 'bd-alti' is served at 25 m only.")
            return self
        if self.resolution_m not in (None, *RGE_ALTI_RESOLUTIONS_M):
            raise ValueError("dataset 'rge-alti' is served at 1 m or 5 m only.")
        unused = [
            name
            for name, used in (
                ("departments", bool(self.departments)),
                ("regions", bool(self.regions)),
                ("file_format", self.file_format.upper() != "ASC"),
                ("crs", self.crs not in (None, "EPSG:2154")),
            )
            if used
        ]
        if unused:
            raise ValueError(
                f"dataset 'rge-alti' is fetched by extent from WMS-Raster; "
                f"{', '.join(unused)} do not apply to it."
            )
        return self


DemSourceConfig: TypeAlias = Annotated[
    CustomDemSource | IgnGeoplateformeDemSource,
    Field(
        discriminator="source",
        description=(
            "Discriminated union of DEM data sources tagged by the 'source' provider key. "
            "Use 'custom' for a user file (TIF/ASC/NC) and "
            "'ign_geoplateforme_dem' for assembled BD ALTI or RGE ALTI retrieval."
        ),
    ),
]


class DemConfig(HydroModelBase):
    """Top-level DEM variable configuration.

    The section declares one or more elevation sources. The loaded DEM can feed
    geographic preprocessing directly or be cached as a reusable data product.

    Example TOML::

        [data.dem]

        [[data.dem.sources]]
        source = "ign_geoplateforme_dem"
        dataset = "bd-alti"
        resolution_m = 25.0
        regions = ["Bretagne"]

        [[data.dem.sources]]
        source = "ign_geoplateforme_dem"
        dataset = "rge-alti"
        resolution_m = 5.0

        [[data.dem.sources]]
        source = "custom"
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
        return cls(sources=[CustomDemSource(path=Path(path), **overrides)])

    @classmethod
    def ign_geoplateforme_dem(cls, **overrides) -> DemConfig:
        """DemConfig pulling an assembled IGN DEM through Geoplateforme."""
        return cls(sources=[IgnGeoplateformeDemSource(**overrides)])
