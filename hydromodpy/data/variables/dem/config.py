"""Pydantic configuration for DEM data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking import InputFile


class _DemSourceBase(HydroModelBase):
    """Shared fields for DEM data sources."""

    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="SHP/GPKG/GeoJSON mask for spatial filtering/clipping.",
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.USER] = Field(
        default=None,
        description="Use project extent for bbox-based data retrieval.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
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
        description=(
            "Optional French administrative regions used to infer department "
            "downloads."
        ),
    )

    @model_validator(mode="after")
    def _check_french_regions(self) -> _FrenchAdministrativeDemSource:
        if str(self.country).upper() == "FR" and self.regions:
            from hydromodpy.data.common.administrative.france import validate_french_regions

            object.__setattr__(self, "regions", validate_french_regions(self.regions))
        return self


class IgnBdaltiDemSource(_FrenchAdministrativeDemSource):
    """IGN BD ALTI 25 m national DEM downloaded per-department."""

    source: Annotated[Literal["ign_bdalti"], Profile.USER] = Field(
        default="ign_bdalti",
        description="Discriminator tag selecting the IGN BD ALTI 25 m DEM provider.",
    )


class IgnGeoplateformeDemSource(_FrenchAdministrativeDemSource):
    """IGN DEM source discovered dynamically through Geoplateforme."""

    source: Annotated[Literal["ign_geoplateforme_dem"], Profile.USER] = Field(
        default="ign_geoplateforme_dem",
        description="Discriminator tag selecting the dynamic IGN Geoplateforme DEM provider.",
    )
    dataset: Annotated[Literal["bd-alti", "rge-alti"], Profile.USER] = Field(
        default="bd-alti",
        description="IGN DEM product to request from Geoplateforme.",
    )
    resolution_m: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description=(
            "Requested DEM resolution in metres. Defaults are resolved by the manager "
            "from the selected dataset."
        ),
    )
    file_format: Annotated[str, Profile.USER] = Field(
        default="ASC",
        description="Requested archive payload format when exposed by Geoplateforme.",
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional CRS filter forwarded to Geoplateforme discovery.",
    )


DemSourceConfig: TypeAlias = Annotated[
    CustomDemSource | IgnBdaltiDemSource | IgnGeoplateformeDemSource,
    Field(
        discriminator="source",
        description=(
            "Discriminated union of DEM data sources tagged by the 'source' provider key. "
            "Use 'custom' for a user file (TIF/ASC/NC), 'ign_bdalti' for the "
            "legacy IGN BD ALTI 25 m MNT path, and 'ign_geoplateforme_dem' for "
            "dynamic IGN DEM discovery."
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
        source = "ign_bdalti"
        regions = ["Bretagne"]

        [[data.dem.sources]]
        source = "ign_geoplateforme_dem"
        dataset = "bd-alti"
        resolution_m = 25.0
        regions = ["Bretagne"]

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
    def ign_bdalti(cls, **overrides) -> DemConfig:
        """DemConfig pulling from the IGN BD ALTI 25 m national DEM."""
        return cls(sources=[IgnBdaltiDemSource(**overrides)])

    @classmethod
    def ign_geoplateforme_dem(cls, **overrides) -> DemConfig:
        """DemConfig pulling an IGN DEM through dynamic Geoplateforme discovery."""
        return cls(sources=[IgnGeoplateformeDemSource(**overrides)])
