"""Pydantic configuration for the rasters of layer bases."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.core.tracking import InputFile


class CustomLayerBaseSource(HydroModelBase):
    """User-provided raster of the base of one layer (GeoTIFF/ASC), elevations in metres.

    A layer of ``[domain.layers]`` reads it by its ``name`` through its ``surface``
    key. The values are elevations in the datum of the DEM.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' layer base provider.",
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


class LayerBaseConfig(HydroModelBase):
    """Top-level layer base variable configuration: one named raster per base.

    Example TOML::

        [[data.layer_base.sources]]
        source = "custom"
        name = "weathered_base"
        path = "data/layer_base/weathered_base.tif"
    """

    sources: Annotated[list[CustomLayerBaseSource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="One raster per layer base, each under its own name.",
    )

    @field_validator("sources")
    @classmethod
    def _names_are_unique(cls, value: list[CustomLayerBaseSource]) -> list[CustomLayerBaseSource]:
        names = [source.name for source in value]
        doubles = sorted({name for name in names if names.count(name) > 1})
        if doubles:
            raise ValueError(f"[[data.layer_base.sources]] names a base twice: {doubles}.")
        return value
