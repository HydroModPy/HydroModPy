"""Pydantic configuration for lake geometry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.core.tracking import InputFile


class CustomLakeGeometrySource(HydroModelBase):
    """User-provided lake geometry file (SHP/GPKG/GeoJSON).

    The vector file holds the lake/reservoir footprint polygon(s) - and, where
    relevant, the dam line and outlet points - that the LAK builder intersects
    with the DISV mesh to resolve the lake cells.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag selecting the 'custom' lake-geometry provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="lake_geometry", category="data"),
    ] = Field(
        ...,
        description="Path to a custom lake-geometry vector file (SHP, GPKG, GeoJSON).",
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "Fallback CRS used only when the file carries none of its own. Defaults to "
            "RGF93/Lambert-93 (EPSG:2154); set it to the site CRS for a non-French dataset."
        ),
    )


class LakeGeometryConfig(HydroModelBase):
    """Top-level lake-geometry variable configuration.

    Example TOML::

        [[data.lake_geometry.sources]]
        source = "custom"
        path = "data/lake_geometry/lake_geometry_custom_lac0.gpkg"
    """

    sources: Annotated[list[CustomLakeGeometrySource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one lake-geometry data source.",
    )
    id: Annotated[IdentifierStr, Profile.USER] = Field(
        default="lake_geometry",
        description="Identifier of the lake-geometry spatial field.",
    )

    @classmethod
    def from_vector(cls, path: str | Path, **overrides) -> LakeGeometryConfig:
        """LakeGeometryConfig from a custom polygon vector file (SHP/GPKG/GeoJSON)."""
        return cls(sources=[CustomLakeGeometrySource(path=Path(path))], **overrides)
