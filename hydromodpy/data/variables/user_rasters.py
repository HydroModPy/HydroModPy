"""Soil capacity, substratum and layer base, the rasters the user brings.

Each one is a file or a url source read in place. Soil capacity and substratum take
exactly one raster, layer base takes one per named layer base.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.families.files import RasterFileVariable
from hydromodpy.data.source.url import UrlSourceOptions

# --- Soil capacity ---------------------------------------------------------


class FileSoilCapacitySource(HydroModelBase):
    """User-provided soil water capacity raster (GeoTIFF/ASC), values in mm."""

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' soil capacity provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="soil_capacity", category="data"),
    ] = Field(
        ...,
        description=(
            "Path to a raster of soil available water capacity in mm (GeoTIFF, ASC). "
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


class UrlSoilCapacitySource(UrlSourceOptions, HydroModelBase):
    """Remote soil capacity raster, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' soil-capacity provider.",
    )


class SoilCapacityConfig(HydroModelBase):
    """Soil available water capacity raster, read by the soil reservoir.

    Example TOML::

        [[data.soil_capacity.sources]]
        source = "file"
        path = "soil/ru_mm.tif"
    """

    sources: Annotated[list[FileSoilCapacitySource | UrlSoilCapacitySource], Profile.USER] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Exactly one soil capacity raster. It spreads the ru of "
            "[flow.sinks_sources.recharge.soil] over classes inside each SAFRAN cell; "
            "ru stays the mean capacity of the cells."
        ),
    )


class SoilCapacityVariable(RasterFileVariable):
    VARIABLE_NAME = "soil_capacity"
    INTERNAL_UNIT = "mm"


# --- Substratum ------------------------------------------------------------


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


class SubstratumVariable(RasterFileVariable):
    VARIABLE_NAME = "substratum"


# --- Layer base ------------------------------------------------------------


class FileLayerBaseSource(HydroModelBase):
    """User-provided raster of the base of one layer (GeoTIFF/ASC), elevations in meters.

    A layer of ``[domain.layers]`` reads it by its ``name`` through its ``surface``
    key. The values are elevations in the datum of the DEM.
    """

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' layer base provider.",
    )
    name: Annotated[IdentifierStr, Profile.USER] = Field(
        ...,
        description=(
            "Name a layer of [[domain.layers.layer]] gives as its surface to end on this base."
        ),
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="layer_base", category="geometry"),
    ] = Field(
        ...,
        description="Path to a raster of the base elevation of a layer in m (GeoTIFF, ASC).",
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a raster that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class UrlLayerBaseSource(UrlSourceOptions, HydroModelBase):
    """Remote layer base raster, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' layer-base provider.",
    )
    name: Annotated[IdentifierStr, Profile.USER] = Field(
        ...,
        description=(
            "Name a layer of [[domain.layers.layer]] gives as its surface to end on this base."
        ),
    )


class LayerBaseConfig(HydroModelBase):
    """Top-level layer base variable configuration: one named raster per base.

    Example TOML::

        [[data.layer_base.sources]]
        source = "file"
        name = "weathered_base"
        path = "data/layer_base/weathered_base.tif"
    """

    sources: Annotated[list[FileLayerBaseSource | UrlLayerBaseSource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="One raster per layer base, each under its own name.",
    )

    @field_validator("sources")
    @classmethod
    def _names_are_unique(
        cls, value: list[FileLayerBaseSource | UrlLayerBaseSource]
    ) -> list[FileLayerBaseSource | UrlLayerBaseSource]:
        names = [source.name for source in value]
        doubles = sorted({name for name in names if names.count(name) > 1})
        if doubles:
            raise ValueError(f"[[data.layer_base.sources]] names a base twice: {doubles}.")
        return value


class LayerBaseVariable(RasterFileVariable):
    VARIABLE_NAME = "layer_base"
